"""Collect the 50 US state label nodes from OSM for literal-name mapping."""

import argparse
from collections import Counter
import json
from pathlib import Path

from scripts.collect_osm_cities import Overpass
from scripts.collect_osm_countries import ENDPOINT, LANGUAGE, TARGET_LANGUAGES, timestamp, write_json

ROOT = Path(__file__).resolve().parents[1]
QUERY = ('[out:json][timeout:180][maxsize:67108864];'
         'area["ISO3166-1"="US"]["boundary"="administrative"]["admin_level"="2"]->.us;'
         'node(area.us)["place"="state"];out body;')
STATES = (
    'Alabama', 'Alaska', 'Arizona', 'Arkansas', 'California', 'Colorado',
    'Connecticut', 'Delaware', 'Florida', 'Georgia', 'Hawaii', 'Idaho',
    'Illinois', 'Indiana', 'Iowa', 'Kansas', 'Kentucky', 'Louisiana',
    'Maine', 'Maryland', 'Massachusetts', 'Michigan', 'Minnesota',
    'Mississippi', 'Missouri', 'Montana', 'Nebraska', 'Nevada',
    'New Hampshire', 'New Jersey', 'New Mexico', 'New York',
    'North Carolina', 'North Dakota', 'Ohio', 'Oklahoma', 'Oregon',
    'Pennsylvania', 'Rhode Island', 'South Carolina', 'South Dakota',
    'Tennessee', 'Texas', 'Utah', 'Vermont', 'Virginia', 'Washington',
    'West Virginia', 'Wisconsin', 'Wyoming',
)


def transform(response):
    if not isinstance(response, dict) or response.get('remark') or not isinstance(response.get('elements'), list):
        raise ValueError('Incomplete Overpass response')
    by_name = {}
    for item in response['elements']:
        if item.get('type') != 'node' or item.get('tags', {}).get('place') != 'state':
            continue
        tags = item['tags']
        name = tags.get('name:en') or tags.get('name')
        if name in STATES:
            by_name.setdefault(name, []).append(item)
    missing = [name for name in STATES if len(by_name.get(name, [])) != 1]
    if missing:
        raise ValueError(f'Expected one OSM state label for every US state; mismatches: {[(n, len(by_name.get(n, []))) for n in missing]}')
    selected = []
    for name in STATES:
        item = by_name[name][0]
        tags = item['tags']
        names = {key[5:]: value for key, value in tags.items()
                 if key.startswith('name:') and LANGUAGE.fullmatch(key[5:]) and value.strip()}
        names['en'] = name
        selected.append({'osm': f'node/{item["id"]}', 'kind': 'state', 'category': 'state',
                         'short_label': name, 'local_name': tags.get('name', name),
                         'names': names, 'location': {'lon': item['lon'], 'lat': item['lat']}})
    if len({item['osm'] for item in selected}) != 50:
        raise ValueError('Duplicate OSM identity among US state labels')
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'work/osm-us-states')
    parser.add_argument('--endpoint', default=ENDPOINT)
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = args.output_dir / 'state-candidates.raw.json'
    if raw_path.exists() and not args.refresh:
        bundle = json.loads(raw_path.read_text(encoding='utf-8'))
        if bundle.get('query') != QUERY or bundle.get('endpoint') != args.endpoint:
            raise ValueError('Cached query or endpoint differs; use --refresh')
    else:
        bundle = {'query': QUERY, 'endpoint': args.endpoint, 'retrieved_at': timestamp(),
                  'response': Overpass(args.endpoint).fetch(QUERY)}
        write_json(raw_path, bundle)
    states = transform(bundle['response'])
    coverage = Counter(lang for state in states for lang in state['names'])
    report = {'selected': len(states), 'target_language_coverage': {lang: coverage[lang] for lang in TARGET_LANGUAGES},
              'query': QUERY, 'endpoint': args.endpoint, 'retrieved_at': bundle['retrieved_at'],
              'generated_at': timestamp(), 'attribution': '© OpenStreetMap contributors',
              'license': 'ODbL-1.0', 'license_url': 'https://www.openstreetmap.org/copyright'}
    write_json(args.output_dir / 'states.json', states)
    write_json(args.output_dir / 'report.json', report)
    print(json.dumps(report, ensure_ascii=True))


if __name__ == '__main__':
    main()
