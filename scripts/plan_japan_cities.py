"""Plan 30 prominent Japanese OSM city labels for five-language meanings."""

import argparse
import json
from pathlib import Path

from backend.config import ROOT, Settings, connect
from scripts.collect_osm_countries import timestamp, write_json


# Explicit OSM IDs separate these cities from namesakes and nearby districts.
CITIES = (
    ('Nara', 'node/1922043513'), ('Yokohama', 'node/1973500311'),
    ('Osaka', 'node/57563779'), ('Nagoya', 'node/569005393'),
    ('Sapporo', 'node/57683926'), ('Fukuoka', 'node/1932338735'),
    ('Kobe', 'node/721818614'), ('Kyoto', 'node/533681139'),
    ('Hiroshima', 'node/1590291928'), ('Sendai', 'node/752184864'),
    ('Chiba', 'node/3675848658'), ('Kitakyushu', 'node/5410283420'),
    ('Sakai', 'node/551364486'), ('Niigata', 'node/752398625'),
    ('Hamamatsu', 'node/763118297'), ('Kumamoto', 'node/642042925'),
    ('Sagamihara', 'node/2115186710'), ('Okayama', 'node/703048335'),
    ('Shizuoka', 'node/763118317'), ('Kagoshima', 'node/640003455'),
    ('Himeji', 'node/721818691'), ('Kanazawa', 'node/303913177'),
    ('Nagasaki', 'node/568515366'), ('Naha', 'node/567940176'),
    ('Matsuyama', 'node/207689592'), ('Utsunomiya', 'node/1108891208'),
    ('Takamatsu', 'node/574804765'), ('Kawasaki', 'node/1933981790'),
    ('Saitama', 'node/243993095'), ('Toyota', 'node/569005466'),
)
LANGUAGES = ('zh', 'en', 'ja', 'fr', 'es')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'work/osm-japan-cities')
    args = parser.parse_args()
    source = json.loads((ROOT / 'work/osm-cities/cities.json').read_text(encoding='utf-8'))
    by_osm = {record['osm']: record for record in source}
    if len(CITIES) != 30 or len({osm for _, osm in CITIES}) != 30:
        raise ValueError('Expected 30 distinct OSM city nodes')
    settings = Settings.from_env()
    selected = []
    with connect(settings) as client:
        for label, osm in CITIES:
            record = by_osm[osm]
            if record['kind'] != 'city' or record['names'].get('en') != label:
                raise ValueError(f'Unexpected OSM English label for {label}')
            japanese = record['names'].get('ja')
            if not japanese or japanese != record['local_name']:
                raise ValueError(f'Missing attested local Japanese name for {label}')
            hits = client.search(index=settings.index,
                query={'term': {'external_ids.osm': osm}}, size=2)['hits']['hits']
            if len(hits) != 1:
                raise ValueError(f'Expected one ES document for {label}, got {len(hits)}')
            doc = hits[0]['_source']
            if doc['kind'] != 'city' or not doc['feature_id']:
                raise ValueError(f'Unexpected ES identity for {label}')
            stored_japanese = doc['names'].get('ja')
            if not stored_japanese:
                raise ValueError(f'Missing Japanese ES spelling for {label}')
            meanings = doc.get('literal_meanings', [])
            complete = bool(meanings) and all(all(m['translations'].get(lang)
                for lang in LANGUAGES) for m in meanings)
            selected.append({
                'label': label, 'osm': osm, 'feature_id': doc['feature_id'],
                'population_osm': record.get('population'),
                'local_name': {'text': stored_japanese, 'lang': 'ja'},
                'existing_literal_name': doc.get('literal_name'),
                'complete': complete, 'location': doc['location'],
            })
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / 'plan-30.json', {
        'created_at': timestamp(), 'index': settings.index,
        'rule': '30 prominent OSM place=city nodes in Japan; attested Japanese OSM names are the original names',
        'selected': selected,
    })
    write_json(args.output_dir / 'feature-ids-30.json',
        [item['feature_id'] for item in selected if not item['complete']])
    print(json.dumps({
        'selected': len(selected), 'complete': sum(item['complete'] for item in selected),
        'pending': sum(not item['complete'] for item in selected),
        'conflicting_originals': sum(bool(item['existing_literal_name']) and
            item['existing_literal_name'] != item['local_name'] for item in selected),
    }, ensure_ascii=True))


if __name__ == '__main__':
    main()
