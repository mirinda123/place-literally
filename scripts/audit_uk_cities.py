"""Audit the additional UK city batch against live Elasticsearch."""

import json

from backend.config import ROOT, Settings, connect
from backend.indexing import Feature
from scripts.collect_osm_countries import timestamp, write_json

LANGUAGES = ('zh', 'en', 'ja', 'fr', 'es')
PLAN = ROOT / 'work/osm-uk-cities/plan-30.json'
OUTPUT = ROOT / 'work/literal-translations/uk-coverage-audit-20260925.json'


def main():
    targets = json.loads(PLAN.read_text(encoding='utf-8'))['selected']
    if len(targets) != 30 or len({t['osm'] for t in targets}) != 30:
        raise ValueError('Expected 30 distinct UK OSM city identities')
    settings = Settings.from_env()
    records = []
    with connect(settings) as client:
        for target in targets:
            hits = client.search(
                index=settings.index,
                query={'term': {'external_ids.osm': target['osm']}},
                size=2,
            )['hits']['hits']
            errors = []
            if len(hits) != 1:
                records.append({
                    'label': target['label'], 'osm': target['osm'],
                    'status': 'identity_error', 'errors': [f'{len(hits)} ES matches'],
                })
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
                errors.append('original name differs from selected OSM English name')
            meanings = doc.get('literal_meanings', [])
            for idx, meaning in enumerate(meanings):
                translations = meaning.get('translations', {})
                missing = [lang for lang in LANGUAGES if not translations.get(lang)]
                if missing:
                    errors.append(f'meaning {idx + 1} missing {missing}')
            status = 'invalid' if errors else 'complete' if meanings else 'uncertain' if original else 'incomplete'
            records.append({
                'label': target['label'], 'nation': target['nation'], 'osm': target['osm'],
                'feature_id': doc['feature_id'], 'status': status,
                'original': original, 'meaning_count': len(meanings),
                'zh_meanings': [m.get('translations', {}).get('zh') for m in meanings],
                'errors': errors,
            })
    summary = {
        'target_count': len(records),
        'complete': sum(r['status'] == 'complete' for r in records),
        'uncertain': sum(r['status'] == 'uncertain' for r in records),
        'incomplete_or_invalid': sum(r['status'] in ('identity_error', 'incomplete', 'invalid') for r in records),
    }
    editorial_review = {
        'Cambridge': 'Corrected the unsupported muddy-river gloss to the attested River Granta; its deeper sense remains uncertain.',
        'Nottingham': 'Removed an unsupported wise-one alternative; the retained personal-name root is still a probable reading.',
        'Birmingham': 'The two readings depend on reconstructed expansions of the unattested personal name Beorma.',
        'Derby': 'The oak-river alternative depends on a disputed adaptation of the River Derwent name.',
        'Dundee': 'Fort of the Tay is supported by Dundee City Council; a competing Daigh reading appears in other place-name references.',
        'Sheffield': 'Boundary as a deeper sense of the River Sheaf is tentative.',
        'Manchester': 'The hill and mother-river readings are competing scholarly reconstructions.',
        'Bangor': 'The enclosure and horn-like-place interpretations compete for the Northern Ireland city.',
        'Leeds': 'The proposed sense of the reconstructed river name is not fully established.',
    }
    write_json(OUTPUT, {
        'generated_at': timestamp(), 'index': settings.index,
        'languages': LANGUAGES, 'summary': summary, 'records': records,
        'editorial_review': editorial_review,
        'draft_notice': 'Model-generated etymological drafts require editorial verification; uncertain roots should not be presented as established.',
    })
    print(json.dumps({'report': str(OUTPUT.resolve()), **summary}, ensure_ascii=True))
    return 0 if summary['incomplete_or_invalid'] == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
