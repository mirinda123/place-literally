"""Audit the 80 selected Indian places, translations, and 512-D vectors."""

import argparse
import json
from pathlib import Path

from backend.config import ROOT, Settings, connect
from backend.indexing import EMBEDDING_FIELD, Feature
from scripts.collect_osm_countries import timestamp, write_json

LANGUAGES = ('zh', 'en', 'ja', 'fr', 'es')


def model_results(run_root):
    results = {}
    for path in sorted((run_root / 'runs').glob('*/report.json')):
        report = json.loads(path.read_text(encoding='utf-8'))
        for item in report.get('items', []):
            cached = None
            if item.get('cache') and item['status'] in ('ready', 'uncertain'):
                cache_path = Path(item['cache'])
                if cache_path.exists():
                    cached = json.loads(cache_path.read_text(encoding='utf-8')).get('result')
            results[item['feature_id']] = {
                'status': item['status'], 'note': cached.get('note') if cached else None,
            }
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=ROOT / 'work/osm-india-places/plan-80.json')
    parser.add_argument('--run-root', type=Path,
                        default=ROOT / 'work/literal-translations/india-places-80-20260927')
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'work/literal-translations/india-places-80-20260927/coverage-audit.json')
    args = parser.parse_args()
    targets = json.loads(args.plan.read_text(encoding='utf-8'))['selected']
    if (len(targets) != 80 or len({item['osm'] for item in targets}) != 80
            or len({item['feature_id'] for item in targets}) != 80
            or sum(item['kind'] == 'city' for item in targets) != 49
            or sum(item['kind'] == 'state' for item in targets) != 31):
        raise ValueError('Expected 49 cities and 31 distinct OSM regions')
    model = model_results(args.run_root)
    editorial_path = args.run_root / 'editorial-decisions.json'
    editorial = (json.loads(editorial_path.read_text(encoding='utf-8'))
                 .get('decisions', {}) if editorial_path.exists() else {})
    settings = Settings.from_env()
    records = []
    with connect(settings) as client:
        for target in targets:
            hits = client.search(index=settings.index,
                query={'term': {'external_ids.osm': target['osm']}}, size=2,
                source_exclude_vectors=False)['hits']['hits']
            errors = []
            if len(hits) != 1:
                records.append({'label': target['label'], 'osm': target['osm'],
                    'kind': target['kind'], 'status': 'identity_error',
                    'errors': [f'{len(hits)} ES matches']})
                continue
            doc = hits[0]['_source']
            if doc['feature_id'] != target['feature_id'] or doc['kind'] != target['kind']:
                errors.append('feature identity or kind mismatch')
            if target['osm'] not in doc.get('external_ids', {}).get('osm', []):
                errors.append('OSM ID mismatch')
            if doc.get('literal_name') != target['local_name']:
                errors.append('original name differs from selected spelling')
            try:
                Feature.model_validate(doc)
            except Exception as exc:
                errors.append(f'schema invalid: {str(exc)[:200]}')
            meanings = doc.get('literal_meanings') or []
            vector_count = 0
            for index, meaning in enumerate(meanings, start=1):
                for lang in LANGUAGES:
                    if not meaning.get('translations', {}).get(lang):
                        errors.append(f'meaning {index} missing {lang} translation')
                    vector = meaning.get(EMBEDDING_FIELD, {}).get(lang)
                    if vector is not None:
                        if len(vector) != 512:
                            errors.append(f'meaning {index} {lang} vector has {len(vector)} dimensions')
                        else:
                            vector_count += 1
            model_result = model.get(target['feature_id'], {})
            editorial_result = editorial.get(target['feature_id'], {})
            status = ('invalid' if errors else 'complete' if meanings else
                      'uncertain' if (model_result.get('status') == 'uncertain'
                                      or editorial_result.get('status') == 'uncertain')
                      else 'incomplete')
            records.append({'label': target['label'], 'osm': target['osm'],
                'feature_id': doc['feature_id'], 'kind': target['kind'],
                'status': status, 'model_status': model_result.get('status'),
                'model_note': model_result.get('note'),
                'editorial_status': editorial_result.get('status'),
                'editorial_reason': editorial_result.get('reason'),
                'original': doc.get('literal_name'),
                'meaning_count': len(meanings),
                'zh_meanings': [item['translations'].get('zh') for item in meanings],
                'vector_count': vector_count,
                'expected_vector_count': len(meanings) * len(LANGUAGES),
                'errors': errors})
    summary = {'target_count': len(records),
        'cities': sum(item['kind'] == 'city' for item in records),
        'regions': sum(item['kind'] == 'state' for item in records),
        'complete': sum(item['status'] == 'complete' for item in records),
        'uncertain': sum(item['status'] == 'uncertain' for item in records),
        'incomplete_or_invalid': sum(item['status'] in ('identity_error', 'incomplete', 'invalid')
                                     for item in records),
        'expected_vectors': sum(item.get('expected_vector_count', 0) for item in records),
        'stored_vectors': sum(item.get('vector_count', 0) for item in records)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, {'generated_at': timestamp(), 'index': settings.index,
        'languages': LANGUAGES, 'summary': summary, 'records': records,
        'draft_notice': 'Model-generated etymologies are provisional until editorial verification.'})
    print(json.dumps({'report': str(args.output.resolve()), **summary}, ensure_ascii=True))
    return 0 if (summary['incomplete_or_invalid'] == 0 and
                 summary['expected_vectors'] == summary['stored_vectors']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
