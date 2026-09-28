"""Audit 30 additional US city names and five-language meanings in ES."""

import json

from backend.config import ROOT, Settings, connect
from backend.indexing import Feature
from scripts.collect_osm_countries import timestamp, write_json

LANGUAGES = ('zh', 'en', 'ja', 'fr', 'es')
PLAN = ROOT / 'work/osm-us-cities/additional-30/plan-30.json'
RUN_ROOT = ROOT / 'work/literal-translations/us-additional-cities-20260925'
OUTPUT = ROOT / 'work/literal-translations/us-additional-coverage-audit-20260925.json'


def model_statuses():
    result = {}
    for path in sorted((RUN_ROOT / 'runs').glob('*/report.json')):
        report = json.loads(path.read_text(encoding='utf-8'))
        for item in report.get('items', []):
            result[item['feature_id']] = item['status']
    return result


def main():
    targets = json.loads(PLAN.read_text(encoding='utf-8'))['selected']
    if len(targets) != 30 or len({t['osm'] for t in targets}) != 30:
        raise ValueError('Expected 30 distinct US city OSM identities')
    statuses = model_statuses()
    settings = Settings.from_env()
    records = []
    with connect(settings) as client:
        for target in targets:
            hits = client.search(index=settings.index,
                query={'term': {'external_ids.osm': target['osm']}}, size=2)['hits']['hits']
            errors = []
            if len(hits) != 1:
                records.append({'label': target['label'], 'osm': target['osm'],
                    'status': 'identity_error', 'errors': [f'{len(hits)} ES matches']})
                continue
            doc = hits[0]['_source']
            if doc['feature_id'] != target['feature_id'] or doc['kind'] != 'city':
                errors.append('feature identity or kind mismatch')
            try:
                Feature.model_validate(doc)
            except Exception as exc:
                errors.append(f'schema invalid: {str(exc)[:200]}')
            original = doc.get('literal_name')
            if original != target['local_name']:
                errors.append('original name differs from the selected English OSM name')
            meanings = doc.get('literal_meanings', [])
            for idx, meaning in enumerate(meanings):
                missing = [lang for lang in LANGUAGES if not meaning.get('translations', {}).get(lang)]
                if missing:
                    errors.append(f'meaning {idx + 1} missing {missing}')
            status = ('invalid' if errors else 'complete' if meanings else
                      'uncertain' if statuses.get(target['feature_id']) == 'uncertain' else 'incomplete')
            records.append({'label': target['label'], 'osm': target['osm'],
                'feature_id': doc['feature_id'], 'status': status,
                'model_status': statuses.get(target['feature_id']), 'original': original,
                'meaning_count': len(meanings),
                'zh_meanings': [m.get('translations', {}).get('zh') for m in meanings],
                'errors': errors})
    summary = {'target_count': len(records),
        'complete': sum(r['status'] == 'complete' for r in records),
        'uncertain': sum(r['status'] == 'uncertain' for r in records),
        'incomplete_or_invalid': sum(r['status'] in ('identity_error', 'incomplete', 'invalid') for r in records)}
    editorial_review = {
        'Tampa': 'The name is linked to an Indigenous place, but no supported lexical sense was found; leave blank.',
        'Albuquerque': 'Three competing readings of the transferred Spanish town name; the stone-tower reading is especially conjectural.',
        'Kansas City': 'Kaw Nation materials support a south-wind reading, while Kansas Historical Society considers the ethnonym meaning unknown.',
        'Milwaukee': 'Two disputed Indigenous-language derivations are shown; do not merge them or assert either as settled.',
        'Wichita': 'The two interpretations come from different proposed source languages and remain disputed.',
        'Orlando': 'The city namesake is disputed; the shown sense is an indirect etymology of the given name.',
        'Saint Paul': 'The small/little reading is the deeper root of the apostle\'s Latin personal name, not a description of the person.',
        'Pittsburgh': 'The pit/hollow reading is an indirect surname etymology; the city directly honors William Pitt.',
    }
    write_json(OUTPUT, {'generated_at': timestamp(), 'index': settings.index,
        'languages': LANGUAGES, 'summary': summary, 'records': records,
        'editorial_review': editorial_review,
        'draft_notice': 'Model-generated etymological drafts need editorial verification; disputed roots should not be presented as established.'})
    print(json.dumps({'report': str(OUTPUT.resolve()), **summary}, ensure_ascii=True))
    return 0 if summary['incomplete_or_invalid'] == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
