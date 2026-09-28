"""Apply two source-checked editorial corrections to the UK city batch."""

import json
from datetime import datetime, timezone

from backend.config import ROOT, Settings, connect
from backend.indexing import Feature
from scripts.collect_osm_countries import timestamp, write_json

OUTPUT_ROOT = ROOT / 'work/literal-translations/uk-cities-20260925/editorial-review'

CORRECTIONS = {
    'osm-node-20971094': {
        'label': 'Cambridge',
        'expected_zh': ['泥水河上的桥'],
        'meanings': [{
            'translations': {
                'zh': '格兰塔河上的桥',
                'en': 'Bridge over the River Granta',
                'ja': 'グランタ川に架かる橋',
                'fr': 'Pont sur la rivière Granta',
                'es': 'Puente sobre el río Granta',
            },
        }],
        'reason': 'The original river was Granta; the proposed muddy-water sense is uncertain.',
        'sources': [
            'https://glossary.lib.cam.ac.uk/term/granta',
            'https://www.snsbi.org.uk/exploring-names/largest-towns-and-cities/',
            'https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1467-968X.2005.00155.x',
        ],
    },
    'osm-node-24913081': {
        'label': 'Nottingham',
        'expected_zh': ['名叫鼻子者的族人聚居地', '智者族人的聚居地'],
        'meanings': [{
            'translations': {
                'zh': '名叫“鼻子”的人的族人聚居地',
                'en': 'Homestead of the people of a man called Nose',
                'ja': '鼻と呼ばれた男の一族の集落',
                'fr': 'Domaine des gens d’un homme appelé Nez',
                'es': 'Asentamiento de la gente de un hombre llamado Nariz',
            },
        }],
        'reason': 'The Snot personal-name reading is documented; the proposed wise-one reading lacks comparable support.',
        'sources': [
            'https://www.snsbi.org.uk/exploring-names/largest-towns-and-cities/',
            'https://pase.ac.uk/domesday/name/2215/',
        ],
    },
}


def main():
    settings = Settings.from_env()
    run_dir = OUTPUT_ROOT / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    run_dir.mkdir(parents=True, exist_ok=False)
    backups = []
    actions = []
    with connect(settings) as client:
        for feature_id, correction in CORRECTIONS.items():
            hit = client.get(index=settings.index, id=feature_id)
            doc = hit['_source']
            before = [m['translations']['zh'] for m in doc['literal_meanings']]
            if doc['feature_id'] != feature_id or doc.get('literal_name') != {'text': correction['label'], 'lang': 'en'}:
                raise ValueError(f'Unexpected original name or identity for {feature_id}')
            if before != correction['expected_zh']:
                raise ValueError(f'Unexpected existing meanings for {feature_id}: {before}')
            patch = {'literal_meanings': correction['meanings'], 'meaning_id': None}
            Feature.model_validate({**doc, **patch})
            backups.append({'index': settings.index, 'hit': dict(hit)})
            actions.append({'feature_id': feature_id, 'label': correction['label'],
                            'before_zh': before, 'after_zh': [m['translations']['zh'] for m in correction['meanings']],
                            'reason': correction['reason'], 'sources': correction['sources']})
        write_json(run_dir / 'before.json', backups)
        for backup, action in zip(backups, actions):
            hit = backup['hit']
            patch = {'literal_meanings': CORRECTIONS[action['feature_id']]['meanings'], 'meaning_id': None}
            client.update(index=settings.index, id=hit['_id'], doc=patch,
                          if_seq_no=hit['_seq_no'], if_primary_term=hit['_primary_term'], refresh='wait_for')
    write_json(run_dir / 'report.json', {'generated_at': timestamp(), 'actions': actions})
    print(json.dumps({'backup_dir': str(run_dir.resolve()), 'corrected': len(actions)}, ensure_ascii=True))


if __name__ == '__main__':
    main()
