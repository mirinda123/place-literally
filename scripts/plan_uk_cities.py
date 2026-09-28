"""Plan 30 additional UK city names from the existing OSM/ES inventory."""

import argparse
import json
from pathlib import Path

from backend.config import ROOT, Settings, connect
from scripts.collect_osm_countries import timestamp, write_json

CITIES = (
    ('Glasgow', 'Scotland'), ('Birmingham', 'England'),
    ('Manchester', 'England'), ('Liverpool', 'England'),
    ('Bristol', 'England'), ('Leeds', 'England'),
    ('Sheffield', 'England'), ('Nottingham', 'England'),
    ('Leicester', 'England'), ('Coventry', 'England'),
    ('Newcastle upon Tyne', 'England'), ('Bradford', 'England'),
    ('Portsmouth', 'England'), ('Southampton', 'England'),
    ('Brighton', 'England'), ('Oxford', 'England'),
    ('Cambridge', 'England'), ('York', 'England'),
    ('Bath', 'England'), ('Plymouth', 'England'),
    ('Cardiff', 'Wales'), ('Swansea', 'Wales'), ('Newport', 'Wales'),
    ('Aberdeen', 'Scotland'), ('Dundee', 'Scotland'),
    ('Derby', 'England'), ('Norwich', 'England'),
    ('Belfast', 'Northern Ireland'), ('Bangor', 'Northern Ireland'),
    ('Lisburn', 'Northern Ireland'),
)
LANGUAGES = ('zh', 'en', 'ja', 'fr', 'es')


def choose(cities, label):
    matches = [record for record in cities
               if record.get('names', {}).get('en') == label or record.get('local_name') == label]
    matches = [record for record in matches if record['kind'] == 'city'
               and -9 < record['location']['lon'] < 2.5
               and 49 < record['location']['lat'] < 59]
    if not matches:
        raise ValueError(f'Missing UK city node: {label}')
    return max(matches, key=lambda record: record.get('population') or 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'work/osm-uk-cities')
    args = parser.parse_args()
    source = json.loads((ROOT / 'work/osm-cities/cities.json').read_text(encoding='utf-8'))
    settings = Settings.from_env()
    selected = []
    with connect(settings) as client:
        for label, nation in CITIES:
            record = choose(source, label)
            hits = client.search(index=settings.index,
                query={'term': {'external_ids.osm': record['osm']}}, size=2)['hits']['hits']
            if len(hits) != 1:
                raise ValueError(f'Expected one ES identity for {label}, got {len(hits)}')
            doc = hits[0]['_source']
            if doc['kind'] != 'city' or doc['names'].get('en', doc['names'].get('und')) != label:
                raise ValueError(f'Unexpected local spelling for {label}: {doc["names"]}')
            meanings = doc.get('literal_meanings', [])
            complete = bool(meanings) and all(all(m['translations'].get(lang)
                for lang in LANGUAGES) for m in meanings)
            selected.append({'label': label, 'nation': nation, 'osm': record['osm'],
                'feature_id': doc['feature_id'], 'population_osm': record.get('population'),
                'local_name': {'text': label, 'lang': 'en'},
                'needs_english_tag': 'en' not in doc['names'],
                'existing_literal_name': doc.get('literal_name'), 'complete': complete,
                'location': doc['location']})
    if len(selected) != len({item['osm'] for item in selected}) or len(selected) != 30:
        raise ValueError('Expected 30 distinct UK city labels')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / 'plan-30.json', {
        'created_at': timestamp(), 'index': settings.index,
        'rule': '30 prominent OSM city labels across England, Scotland, Wales and Northern Ireland, excluding previously batched London and Edinburgh',
        'selected': selected})
    write_json(args.output_dir / 'feature-ids-30.json', [item['feature_id'] for item in selected])
    print(json.dumps({'selected': len(selected),
        'complete': sum(item['complete'] for item in selected),
        'pending': sum(not item['complete'] for item in selected),
        'missing_en_tags': sum(item['needs_english_tag'] for item in selected)}, ensure_ascii=True))


if __name__ == '__main__':
    main()
