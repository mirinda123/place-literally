"""Audit the additional Chinese city batch against ES and its OSM identities."""

import json
from pathlib import Path

from backend.config import ROOT, Settings, connect
from backend.indexing import Feature
from scripts.collect_osm_countries import timestamp, write_json


LANGUAGES = ('zh', 'en', 'ja', 'fr', 'es')
PLAN = ROOT / 'work/osm-china-cities/additional-30/plan-30.json'
RUN_ROOT = ROOT / 'work/literal-translations/china-additional-cities-20260925'
OUTPUT = ROOT / 'work/literal-translations/china-additional-coverage-audit-20260925.json'


def model_results():
    result = {}
    for path in sorted((RUN_ROOT / 'runs').glob('*/report.json')):
        report = json.loads(path.read_text(encoding='utf-8'))
        for item in report.get('items', []):
            cached = None
            if item.get('cache') and item['status'] in ('ready', 'uncertain'):
                cache_path = Path(item['cache'])
                if cache_path.exists():
                    cached = json.loads(cache_path.read_text(encoding='utf-8')).get('result')
            result[item['feature_id']] = {'status': item['status'], 'note':
                cached.get('note') if cached else None}
    return result


def main():
    targets = json.loads(PLAN.read_text(encoding='utf-8'))['selected']
    if len(targets) != 30 or len({t['osm'] for t in targets}) != 30:
        raise ValueError('Expected 30 distinct Chinese OSM city nodes')
    model = model_results()
    correction_path = RUN_ROOT / 'editorial-corrections.json'
    corrections = (json.loads(correction_path.read_text(encoding='utf-8'))['corrections']
                   if correction_path.exists() else [])
    editorial_uncertain = {item['feature_id'] for item in corrections
                           if item.get('status') == 'uncertain'}
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
            if target['osm'] not in doc.get('external_ids', {}).get('osm', []):
                errors.append('OSM ID mismatch')
            try:
                Feature.model_validate(doc)
            except Exception as exc:
                errors.append(f'schema invalid: {str(exc)[:200]}')
            original = doc.get('literal_name')
            if original != target['local_name']:
                errors.append('original name differs from selected Chinese spelling')
            meanings = doc.get('literal_meanings', [])
            for idx, meaning in enumerate(meanings):
                missing = [lang for lang in LANGUAGES
                           if not meaning.get('translations', {}).get(lang)]
                if missing:
                    errors.append(f'meaning {idx + 1} missing {missing}')
            model_result = model.get(target['feature_id'], {})
            status = ('invalid' if errors else 'complete' if meanings else
                      'uncertain' if target['feature_id'] in editorial_uncertain or
                      model_result.get('status') == 'uncertain' else 'incomplete')
            records.append({'label': target['label'], 'osm': target['osm'],
                'feature_id': doc['feature_id'], 'status': status,
                'model_status': model_result.get('status'), 'model_note': model_result.get('note'),
                'original': original, 'meaning_count': len(meanings),
                'zh_meanings': [m.get('translations', {}).get('zh') for m in meanings],
                'errors': errors})
    summary = {'target_count': len(records),
        'complete': sum(r['status'] == 'complete' for r in records),
        'uncertain': sum(r['status'] == 'uncertain' for r in records),
        'incomplete_or_invalid': sum(r['status'] in ('identity_error', 'incomplete', 'invalid')
                                     for r in records)}
    editorial_review = {
        'Harbin': 'Three published source-language interpretations remain contested.',
        'Kaohsiung': 'Bamboo grove is the widely used reading; chicken and surf readings are competing minority interpretations.',
        'Ürümqi': 'The conventional beautiful-pasture reading and a historical White Water proposal conflict.',
        'Yinchuan': 'The silver-plain reading and older transferred-place-name hypothesis are competing explanations.',
        'Xuzhou': 'The Xu people, the terrain gloss and Xu Hill are distinct historical proposals, not cumulative parts of one name.',
    }
    write_json(OUTPUT, {'generated_at': timestamp(), 'index': settings.index,
        'languages': LANGUAGES, 'summary': summary, 'records': records,
        'editorial_corrections': corrections, 'editorial_review': editorial_review,
        'draft_notice': 'Model-generated name interpretations require editorial verification, especially names transcribed from non-Chinese languages.'})
    print(json.dumps({'report': str(OUTPUT.resolve()), **summary}, ensure_ascii=False))
    return 0 if summary['incomplete_or_invalid'] == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
