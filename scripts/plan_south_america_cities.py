"""Plan 40 untranslated South American cities from country-scoped OSM exports."""

import argparse
import json
from pathlib import Path

from backend.config import ROOT, Settings, connect
from scripts.collect_osm_countries import timestamp, write_json


# The quotas cover every sovereign mainland South American country while
# weighting larger urban systems more heavily. No translated seed is reused.
QUOTAS = {
    'BR': (9, 'pt'), 'AR': (6, 'es'), 'CO': (4, 'es'),
    'PE': (3, 'es'), 'CL': (3, 'es'), 'VE': (3, 'es'),
    'EC': (3, 'es'), 'BO': (3, 'es'), 'PY': (2, 'es'),
    'UY': (2, 'es'), 'GY': (1, 'en'), 'SR': (1, 'nl'),
}
LANGUAGES = ('zh', 'en', 'ja', 'fr', 'es')
# For these major cities OSM's primary `name` is the locally used spelling,
# but the same spelling lacks a dedicated `name:<language>` tag. This is a
# reviewed, ID-bound fallback; it never translates from `name:en` or guesses
# an Indigenous etymology from the modern display language.
REVIEWED_PRIMARY_NAMES = {
    'node/34593849': ('pt', 'Salvador'),
    'node/198403560': ('es', 'Mendoza'),
    'node/247782633': ('es', 'La Plata'),
    'node/198402188': ('es', 'Mar del Plata'),
    'node/344799743': ('es', 'Medellín'),
    'node/214220794': ('es', 'Antofagasta'),
    'node/50026147': ('es', 'Viña del Mar'),
    'node/7179881094': ('es', 'Valencia'),
    'node/9911249241': ('es', 'Cuenca'),
    'node/568203308': ('es', 'El Alto'),
    'node/1975648720': ('es', 'La Paz'),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cities', type=Path,
                        default=ROOT / 'work/osm-south-america-cities/cities.json')
    parser.add_argument('--output-dir', type=Path,
                        default=ROOT / 'work/osm-south-america-cities/selected-40')
    args = parser.parse_args()
    if sum(count for count, _ in QUOTAS.values()) != 40:
        raise ValueError('The South America quotas must total 40')
    cities = json.loads(args.cities.read_text(encoding='utf-8'))
    if {scope for item in cities for scope in item['query_scopes']} != set(QUOTAS):
        raise ValueError('Country-scoped source is missing or has unexpected countries')
    settings = Settings.from_env()
    selected, skipped = [], {}
    with connect(settings) as client:
        for country, (quota, lang) in QUOTAS.items():
            candidates = sorted(
                (item for item in cities if item['kind'] == 'city'
                 and country in item['query_scopes']),
                key=lambda item: (item.get('population') or 0,
                                  item['osm']), reverse=True)
            picks = []
            for item in candidates:
                if len(picks) == quota:
                    break
                osm = item['osm']
                original = item['names'].get(lang)
                if not original and osm in REVIEWED_PRIMARY_NAMES:
                    fallback_lang, fallback_name = REVIEWED_PRIMARY_NAMES[osm]
                    if lang != fallback_lang or item['local_name'] != fallback_name:
                        raise ValueError(f'Reviewed primary name changed for {osm}')
                    original = item['local_name']
                if not original or not original.strip():
                    skipped[item['osm']] = f'no attested {lang} spelling'
                    continue
                hits = client.search(index=settings.index,
                                     query={'term': {'external_ids.osm': osm}},
                                     size=2)['hits']['hits']
                if len(hits) != 1:
                    skipped[osm] = f'{len(hits)} ES matches'
                    continue
                doc = hits[0]['_source']
                if (doc['kind'] != 'city' or
                        doc['feature_id'] != f'osm-{osm.replace("/", "-")}' or
                        osm not in doc.get('external_ids', {}).get('osm', [])):
                    raise ValueError(f'Unexpected ES identity for {osm}')
                if doc.get('literal_name') or doc.get('literal_meanings'):
                    skipped[osm] = 'already pinned or translated'
                    continue
                if original not in doc.get('names', {}).values():
                    raise ValueError(f'OSM original spelling not in ES for {osm}')
                pick = {'label': item['names'].get('en') or item['local_name'],
                        'country': country, 'osm': osm,
                        'feature_id': doc['feature_id'], 'kind': 'city',
                        'local_name': {'text': original, 'lang': lang},
                        'needs_language_tag': doc['names'].get(lang) != original,
                        'location': doc['location'],
                        'population_osm': item.get('population')}
                picks.append(pick)
                selected.append(pick)
            if len(picks) != quota:
                raise ValueError(f'{country} has {len(picks)} eligible cities, expected {quota}')
    if len(selected) != 40 or len({item['osm'] for item in selected}) != 40:
        raise ValueError('Expected 40 unique OSM city nodes')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / 'plan-40.json', {
        'created_at': timestamp(), 'index': settings.index,
        'rule': '40 untranslated major OSM cities across 12 South American countries',
        'quota_by_country': {key: count for key, (count, _) in QUOTAS.items()},
        'languages': LANGUAGES, 'selected': selected,
        'skipped': skipped,
    })
    write_json(args.output_dir / 'feature-ids-40.json',
               [item['feature_id'] for item in selected])
    print(json.dumps({'index': settings.index, 'selected': len(selected),
                      'countries': len(QUOTAS),
                      'output': str(args.output_dir.resolve())}, ensure_ascii=True))


if __name__ == '__main__':
    main()
