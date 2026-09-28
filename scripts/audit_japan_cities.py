"""Audit Japanese city origins, five-language meanings, and OSM identities."""

import json

from backend.config import ROOT, Settings, connect
from backend.indexing import Feature
from scripts.collect_osm_countries import timestamp, write_json

LANGUAGES = ('zh', 'en', 'ja', 'fr', 'es')
PLAN = ROOT / 'work/osm-japan-cities/plan-30.json'
RUN_ROOT = ROOT / 'work/literal-translations/japan-cities-20260925'
OUTPUT = ROOT / 'work/literal-translations/japan-coverage-audit-20260925.json'


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
        raise ValueError('Expected 30 distinct Japanese OSM city nodes')
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
                errors.append('original name differs from the selected Japanese name')
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
        'Sapporo': 'Two Ainu-language readings are documented by Sapporo City; neither is established as the unique origin.',
        'Naha': 'Fishing-ground and mushroom-shaped-rock readings are competing Okinawan accounts.',
        'Saitama': 'The three readings are proposals for ancient Sakitama, not meanings of the modern hiragana spelling.',
        'Nagoya': 'Three historical proposals remain unresolved; the present-day characters do not establish a lexical sense.',
        'Kagoshima': 'Three deeper roots remain disputed; old phonographic spellings should not be translated as modern kanji.',
        'Osaka': 'Small slope follows an older spelling, but the city says the ultimate origin is uncertain.',
        'Fukuoka': 'The city name was transferred from Bizen Fukuoka; the written good-fortune hill sense does not prove that older settlement\'s original naming motive.',
        'Hiroshima': 'Wide island is one reading; a separate commemorative account explains character choice rather than another lexical meaning.',
        'Sendai': 'The thousand-Buddha explanation is a historical tradition, not a demonstrated origin.',
        'Hamamatsu': 'The shore-port and shore-pines readings depend on the relationship between old and later spellings.',
        'Kumamoto': 'The two interpretations of the old place-name remain disputed; modern bear is a later character choice.',
        'Shizuoka': 'Corrected the Chinese gloss to preserve 賤機 as a proper mountain name; its deeper root is not established.',
    }
    write_json(OUTPUT, {'generated_at': timestamp(), 'index': settings.index,
        'languages': LANGUAGES, 'summary': summary, 'records': records,
        'editorial_review': editorial_review,
        'draft_notice': 'Model-generated etymological drafts need editorial verification, especially Ainu and Ryukyuan name roots.'})
    print(json.dumps({'report': str(OUTPUT.resolve()), **summary}, ensure_ascii=True))
    return 0 if summary['incomplete_or_invalid'] == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
