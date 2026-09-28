"""Audit the planned European city batch against live Elasticsearch."""

import json

from backend.config import ROOT, Settings, connect
from backend.indexing import Feature
from scripts.collect_osm_countries import timestamp, write_json

LANGUAGES = ('zh', 'en', 'ja', 'fr', 'es')
OUTPUT = ROOT / 'work/literal-translations/europe-coverage-audit-20260925.json'


def main():
    plan = json.loads((ROOT / 'work/osm-europe-cities/plan-45.json').read_text(encoding='utf-8'))
    targets = plan['selected']
    if len(targets) != 45 or len({t['osm'] for t in targets}) != 45:
        raise ValueError('Expected 45 distinct OSM city identities')
    settings = Settings.from_env()
    records = []
    with connect(settings) as client:
        for target in targets:
            hits = client.search(index=settings.index, query={'term': {'external_ids.osm': target['osm']}}, size=2)['hits']['hits']
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
                errors.append('original name differs from selected local OSM name')
            meanings = doc.get('literal_meanings', [])
            for idx, meaning in enumerate(meanings):
                missing = [lang for lang in LANGUAGES if not meaning.get('translations', {}).get(lang)]
                if missing:
                    errors.append(f'meaning {idx + 1} missing {missing}')
            status = 'invalid' if errors else 'complete' if meanings else 'uncertain' if original else 'incomplete'
            records.append({'label': target['label'], 'osm': target['osm'],
                            'feature_id': doc['feature_id'], 'status': status,
                            'original': original, 'meaning_count': len(meanings),
                            'zh_meanings': [m.get('translations', {}).get('zh') for m in meanings],
                            'errors': errors})
    summary = {'target_count': len(records),
               'complete': sum(r['status'] == 'complete' for r in records),
               'uncertain': sum(r['status'] == 'uncertain' for r in records),
               'incomplete_or_invalid': sum(r['status'] in ('identity_error', 'incomplete', 'invalid') for r in records)}
    editorial_review = {
        'Barcelona': 'Older Barkeno is attested, but no reliable lexical sense was recovered; leave blank.',
        'Lisbon': 'Ancient Olisipo has no established full lexical sense; leave blank.',
        'Athens': 'Association with Athena does not establish the pre-Greek root; leave blank.',
        'London': 'Both ancient-name readings are disputed reconstructions.',
        'Paris': 'Three scholarly proposals for the Parisii ethnonym remain disputed.',
        'Rome': 'Etruscan family-name origin is favored; the two shown lexical readings are alternatives.',
        'Seville': 'Early Hispal(is) is disputed; all three shown readings need closer editorial source review.',
        'Venice': 'Proposed deeper sense of Veneti is approximate, not a secure ancient translation.',
        'Kyiv': 'Do not treat the traditional Kyi founding story as proof of the proposed word root.',
        'Ljubljana': 'Two competing reconstructed naming chains; neither is established.',
    }
    write_json(OUTPUT, {'generated_at': timestamp(), 'index': settings.index,
                        'languages': LANGUAGES, 'summary': summary, 'records': records,
                        'editorial_review': editorial_review,
                        'draft_notice': 'Model-generated etymological drafts are not scholarly verification; disputed roots require editorial review.'})
    print(json.dumps({'report': str(OUTPUT.resolve()), **summary}, ensure_ascii=True))
    return 0 if summary['incomplete_or_invalid'] == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
