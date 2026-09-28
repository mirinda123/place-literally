"""Audit the US state and major-city translation batches against live Elasticsearch."""

import json
from pathlib import Path

from backend.config import ROOT, Settings, connect
from backend.indexing import Feature
from scripts.collect_osm_countries import timestamp, write_json

LANGUAGES = ('zh', 'en', 'ja', 'fr', 'es')
OUTPUT = ROOT / 'work/literal-translations/us-coverage-audit-20260925.json'


def main():
    states = json.loads((ROOT / 'work/osm-us-states/states.json').read_text(encoding='utf-8'))
    cities = json.loads((ROOT / 'work/osm-us-cities/plan-30.json').read_text(encoding='utf-8'))['selected']
    targets = [('state', item['short_label'], item['osm']) for item in states]
    targets += [('city', item['label'], item['osm']) for item in cities]
    if len(targets) != 80 or len({osm for _, _, osm in targets}) != 80:
        raise ValueError('Expected 50 states and 30 distinct cities')
    settings = Settings.from_env()
    records = []
    with connect(settings) as client:
        for kind, label, osm in targets:
            hits = client.search(index=settings.index, query={'term': {'external_ids.osm': osm}}, size=2)['hits']['hits']
            errors = []
            if len(hits) != 1:
                records.append({'kind': kind, 'label': label, 'osm': osm,
                                'status': 'identity_error', 'errors': [f'{len(hits)} ES matches']})
                continue
            doc = hits[0]['_source']
            if doc.get('kind') != kind:
                errors.append('kind mismatch')
            try:
                Feature.model_validate(doc)
            except Exception as exc:
                errors.append(f'schema invalid: {str(exc)[:200]}')
            original = doc.get('literal_name')
            if original and (original.get('lang') == 'und' or original.get('text') not in doc.get('names', {}).values()):
                errors.append('original name not found in names')
            meanings = doc.get('literal_meanings', [])
            for idx, meaning in enumerate(meanings):
                missing = [lang for lang in LANGUAGES if not meaning.get('translations', {}).get(lang)]
                if missing:
                    errors.append(f'meaning {idx + 1} missing {missing}')
            status = 'invalid' if errors else 'complete' if original and meanings else 'uncertain' if not original and not meanings else 'incomplete'
            records.append({'kind': kind, 'label': label, 'osm': osm,
                            'feature_id': doc.get('feature_id'), 'status': status,
                            'original': original, 'meaning_count': len(meanings),
                            'zh_meanings': [m.get('translations', {}).get('zh') for m in meanings],
                            'errors': errors})
    summary = {'target_count': len(records), 'states': sum(x['kind'] == 'state' for x in records),
               'cities': sum(x['kind'] == 'city' for x in records),
               'complete': sum(x['status'] == 'complete' for x in records),
               'uncertain': sum(x['status'] == 'uncertain' for x in records),
               'incomplete_or_invalid': sum(x['status'] in ('identity_error', 'incomplete', 'invalid') for x in records)}
    report = {'generated_at': timestamp(), 'index': settings.index, 'languages': LANGUAGES,
              'summary': summary, 'records': records,
              'editorial_review': {
                  'new-york-us': 'Re-reviewed and manually tightened the Eburos alternative.',
                  'Pennsylvania': "Corrected to Penn's woods from state government and historical sources.",
                  'Idaho': 'Left uncertain: Idaho historical sources say the exact source of its coined name is unknown.',
                  'California': 'Generated caliph reading is speculative and should receive further editorial review.',
                  'New Jersey': 'The three deeper Jersey derivations are contested and should receive further editorial review.',
              }}
    write_json(OUTPUT, report)
    print(json.dumps({'report': str(OUTPUT.resolve()), **summary}, ensure_ascii=True))
    return 0 if summary['incomplete_or_invalid'] == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
