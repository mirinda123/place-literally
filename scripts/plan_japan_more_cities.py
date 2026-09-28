"""Plan 50 further Japanese OSM cities with attested Japanese originals."""

import argparse
import json
from pathlib import Path

from backend.config import ROOT, Settings, connect
from scripts.collect_osm_countries import timestamp, write_json


# Explicit nodes keep Chinese cities, Tokyo wards, and Japanese namesakes out.
CITIES = (
    ('Funabashi', 'node/264883234'), ('Kawaguchi', 'node/864262454'),
    ('Hachioji', 'node/622423997'), ('Higashiosaka', 'node/551367401'),
    ('Ichikawa', 'node/2098146352'), ('Nishinomiya', 'node/721818484'),
    ('Matsudo', 'node/2098183361'), ('Kurashiki', 'node/703049817'),
    ('Oita', 'node/417258484'), ('Fukuyama', 'node/1985508816'),
    ('Amagasaki', 'node/721818337'), ('Fujisawa', 'node/2115184122'),
    ('Machida', 'node/623797057'), ('Kashiwa', 'node/2098183362'),
    ('Toyama', 'node/762306892'), ('Gifu', 'node/5488948282'),
    ('Hirakata', 'node/551368349'), ('Miyazaki', 'node/739203629'),
    ('Toyonaka', 'node/551367193'), ('Yokosuka', 'node/2115184112'),
    ('Okazaki', 'node/569005455'), ('Ichinomiya', 'node/569005518'),
    ('Suita', 'node/551367260'), ('Toyohashi', 'node/569005441'),
    ('Nagano', 'node/702987391'), ('Takasaki', 'node/1068823649'),
    ('Wakayama', 'node/1551511175'), ('Takatsuki', 'node/551368471'),
    ('Kawagoe', 'node/537121807'), ('Iwaki', 'node/734866076'),
    ('Koshigaya', 'node/864255939'), ('Tokorozawa', 'node/863622554'),
    ('Otsu', 'node/541402993'), ('Asahikawa', 'node/184366763'),
    ('Koriyama', 'node/734866104'), ('Kochi', 'node/574820566'),
    ('Maebashi', 'node/574841107'), ('Akita', 'node/752195639'),
    ('Yokkaichi', 'node/623153598'), ('Kurume', 'node/3056729963'),
    ('Kasugai', 'node/569005542'), ('Akashi', 'node/721818502'),
    ('Morioka', 'node/471357225'), ('Nagaoka', 'node/752398736'),
    ('Fukushima', 'node/734866113'), ('Aomori', 'node/734876517'),
    ('Mito', 'node/736355846'), ('Fukui', 'node/762073174'),
    ('Shimonoseki', 'node/697538044'), ('Tokushima', 'node/263264345'),
)
LANGUAGES = ('zh', 'en', 'ja', 'fr', 'es')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path,
                        default=ROOT / 'work/osm-japan-cities/additional-50')
    args = parser.parse_args()
    if len(CITIES) != 50 or len({osm for _, osm in CITIES}) != 50:
        raise ValueError('Expected 50 distinct Japanese OSM nodes')
    source = json.loads((ROOT / 'work/osm-cities/cities.json').read_text(encoding='utf-8'))
    by_osm = {record['osm']: record for record in source}
    prior = json.loads((ROOT / 'work/osm-japan-cities/plan-30.json').read_text(encoding='utf-8'))
    previous = {item['osm'] for item in prior['selected']}
    settings = Settings.from_env()
    selected = []
    with connect(settings) as client:
        for label, osm in CITIES:
            if osm in previous:
                raise ValueError(f'Already in first Japanese batch: {label}')
            record = by_osm[osm]
            japanese = record.get('names', {}).get('ja')
            if (record['kind'] != 'city' or record.get('names', {}).get('en') != label
                    or not japanese or record['local_name'] != japanese):
                raise ValueError(f'Unexpected OSM city name for {label}: {record}')
            lon, lat = record['location']['lon'], record['location']['lat']
            if not (127 <= lon <= 146 and 30 <= lat <= 46):
                raise ValueError(f'Outside Japanese city region: {label}')
            hits = client.search(index=settings.index,
                query={'term': {'external_ids.osm': osm}}, size=2)['hits']['hits']
            if len(hits) != 1:
                raise ValueError(f'Expected one ES document for {label}, got {len(hits)}')
            doc = hits[0]['_source']
            if doc['kind'] != 'city' or doc['feature_id'] != f'osm-{osm.replace("/", "-")}':
                raise ValueError(f'Unexpected ES identity for {label}')
            if doc['names'].get('ja') != japanese:
                raise ValueError(f'Japanese name mismatch for {label}')
            if doc.get('literal_name') or doc.get('literal_meanings'):
                raise ValueError(f'Already translated or pinned: {label}')
            selected.append({'label': label, 'osm': osm, 'feature_id': doc['feature_id'],
                'population_osm': record.get('population'),
                'local_name': {'text': japanese, 'lang': 'ja'},
                'location': doc['location'], 'complete': False})
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / 'plan-50.json', {
        'created_at': timestamp(), 'index': settings.index,
        'rule': '50 further Japanese OSM place=city nodes, excluding the previous 30 cities and Tokyo seed',
        'selected': selected,
    })
    write_json(args.output_dir / 'feature-ids-50.json', [item['feature_id'] for item in selected])
    print(json.dumps({'selected': len(selected)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
