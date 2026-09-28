"""Cache India's OSM state/province place nodes for a curated region batch."""

import argparse
import json
from pathlib import Path

from scripts.collect_osm_cities import Overpass, validate
from scripts.collect_osm_countries import ENDPOINT, LANGUAGE, timestamp, write_json

ROOT = Path(__file__).resolve().parents[1]
QUERY = ('[out:json][timeout:180][maxsize:67108864];'
         'area["ISO3166-1"="IN"]["boundary"="administrative"]["admin_level"="2"]->.country;'
         '.country out tags;'
         'node(area.country)["place"~"^(state|province)$"];out body;')
EXPECTED = {
    'Andaman and Nicobar Islands', 'Andhra Pradesh', 'Arunachal Pradesh', 'Assam',
    'Bihar', 'Chhattisgarh', 'Delhi', 'Goa', 'Gujarat', 'Haryana',
    'Himachal Pradesh', 'Jammu and Kashmir', 'Jharkhand', 'Karnataka', 'Kerala',
    'Ladakh', 'Madhya Pradesh', 'Maharashtra', 'Manipur', 'Meghalaya', 'Mizoram',
    'Nagaland', 'Odisha', 'Punjab', 'Rajasthan', 'Tamil Nadu', 'Telangana',
    'Tripura', 'Uttar Pradesh', 'Uttarakhand', 'West Bengal',
}
UNMATCHED_OFFICIAL = ('Sikkim', 'Chandigarh', 'Dadra and Nagar Haveli and Daman and Diu',
                      'Lakshadweep', 'Puducherry')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'work/osm-india-regions')
    parser.add_argument('--endpoint', default=ENDPOINT)
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = args.output_dir / 'state-candidates.raw.json'
    if raw_path.exists() and not args.refresh:
        bundle = json.loads(raw_path.read_text(encoding='utf-8'))
        if bundle.get('query') != QUERY or bundle.get('endpoint') != args.endpoint:
            raise ValueError('Cached query or endpoint differs; use --refresh')
        validate(bundle['response'], 'IN')
    else:
        bundle = {'query': QUERY, 'endpoint': args.endpoint, 'retrieved_at': timestamp(),
                  'response': Overpass(args.endpoint).fetch(QUERY, 'IN')}
        write_json(raw_path, bundle)
    nodes = [item for item in bundle['response']['elements'] if item['type'] == 'node']
    summary = [{'osm': f"node/{item['id']}", 'kind': item['tags']['place'],
                'name': item['tags'].get('name'), 'en': item['tags'].get('name:en'),
                'hi': item['tags'].get('name:hi')}
               for item in nodes]
    write_json(args.output_dir / 'candidates.json', summary)
    labels = [item['en'] or item['name'] for item in summary]
    if len(nodes) != 31 or len(set(labels)) != 31 or set(labels) != EXPECTED:
        raise ValueError(f'India region-node set changed: missing={sorted(EXPECTED-set(labels))}, extra={sorted(set(labels)-EXPECTED)}')
    regions = []
    for item, label in zip(nodes, labels):
        tags = item['tags']
        names = {key[5:]: value for key, value in tags.items()
                 if key.startswith('name:') and LANGUAGE.fullmatch(key[5:]) and value.strip()}
        names['en'] = label
        regions.append({'osm': f"node/{item['id']}", 'kind': 'state',
                        'category': 'state_or_union_territory', 'short_label': label,
                        'local_name': tags['name'], 'names': names,
                        'location': {'lon': item['lon'], 'lat': item['lat']}})
    write_json(args.output_dir / 'regions.json', regions)
    report = {'selected': len(regions), 'unmatched_official_regions': UNMATCHED_OFFICIAL,
              'source': 'https://www.india.gov.in/explore-india/odop',
              'osm_attribution': '© OpenStreetMap contributors', 'license': 'ODbL-1.0',
              'license_url': 'https://www.openstreetmap.org/copyright',
              'retrieved_at': bundle['retrieved_at'], 'generated_at': timestamp()}
    write_json(args.output_dir / 'report.json', report)
    print(json.dumps(report, ensure_ascii=True))


if __name__ == '__main__':
    main()
