"""Choose 30 prominent US city labels from the existing OSM/ES inventory."""

import argparse
import json
from pathlib import Path

from backend.config import ROOT, Settings, connect
from scripts.collect_osm_countries import timestamp, write_json

CITY_NAMES = (
    'New York City', 'Los Angeles', 'Chicago', 'Houston', 'Phoenix',
    'Philadelphia', 'San Antonio', 'San Diego', 'Dallas', 'Jacksonville',
    'Fort Worth', 'San Jose', 'Austin', 'Charlotte', 'Columbus',
    'Indianapolis', 'San Francisco', 'Seattle', 'Denver', 'Washington',
    'Boston', 'Nashville', 'Detroit', 'Oklahoma City', 'Portland',
    'Las Vegas', 'Miami', 'Atlanta', 'Minneapolis', 'New Orleans',
)
NEW_YORK_OSM = 'node/61785451'


def choose(cities, name):
    candidates = [record for record in cities
                  if record.get('names', {}).get('en') == name or record.get('local_name') == name]
    # These curated hubs are all in the contiguous US. This rejects namesakes abroad.
    candidates = [record for record in candidates
                  if -125 <= record['location']['lon'] <= -66 and 24 <= record['location']['lat'] <= 50]
    if not candidates:
        raise ValueError(f'Missing US city label: {name}')
    return max(candidates, key=lambda record: record.get('population') or 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'work/osm-us-cities')
    args = parser.parse_args()
    cities = json.loads((ROOT / 'work/osm-cities/cities.json').read_text(encoding='utf-8'))
    selected = []
    settings = Settings.from_env()
    with connect(settings) as client:
        for name in CITY_NAMES:
            record = {'osm': NEW_YORK_OSM, 'local_name': 'New York', 'population': None,
                      'selection': 'existing_seed'} if name == 'New York City' else choose(cities, name)
            hits = client.search(index=settings.index, query={'term': {'external_ids.osm': record['osm']}}, size=2)['hits']['hits']
            if len(hits) != 1:
                raise ValueError(f'Expected one ES match for {name} / {record["osm"]}, found {len(hits)}')
            doc = hits[0]['_source']
            if doc['kind'] != 'city':
                raise ValueError(f'Not a city: {name} / {doc["kind"]}')
            meanings = doc.get('literal_meanings', [])
            complete = bool(meanings) and all(all(m['translations'].get(lang)
                for lang in ('zh', 'en', 'ja', 'fr', 'es')) for m in meanings)
            selected.append({'label': name, 'osm': record['osm'], 'feature_id': doc['feature_id'],
                             'population_osm': record.get('population'), 'complete': complete,
                             'location': doc['location']})
    if len(selected) != len(set(item['osm'] for item in selected)) or len(selected) != 30:
        raise ValueError('City list must contain 30 distinct OSM labels')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    plan = {'created_at': timestamp(), 'index': settings.index,
            'rule': '30 curated prominent city labels; for duplicate names choose the US OSM node with highest tagged population',
            'selected': selected}
    write_json(args.output_dir / 'plan-30.json', plan)
    write_json(args.output_dir / 'feature-ids-30.json', [item['feature_id'] for item in selected])
    print(json.dumps({'selected': len(selected), 'complete': sum(item['complete'] for item in selected),
                      'pending': sum(not item['complete'] for item in selected)}, ensure_ascii=True))


if __name__ == '__main__':
    main()
