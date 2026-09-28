"""Plan 50 further European OSM city nodes with locally used original names."""

import argparse
import json
from pathlib import Path

from backend.config import ROOT, Settings, connect
from scripts.collect_osm_countries import timestamp, write_json


# Curated nodes avoid namesakes outside Europe and the 45+30 earlier cities.
# The language tag identifies the spelling to explain, not a translation target.
CITIES = (
    ('Marseille', 'node/26761400', 'fr'), ('Lyon', 'node/20626319', 'fr'),
    ('Toulouse', 'node/26686518', 'fr'), ('Nice', 'node/1701090139', 'fr'),
    ('Nantes', 'node/26686548', 'fr'), ('Strasbourg', 'node/26686563', 'fr'),
    ('Bordeaux', 'node/1691675873', 'fr'), ('Lille', 'node/26686577', 'fr'),
    ('Cologne', 'node/20953083', 'de'), ('Frankfurt', 'node/27418664', 'de'),
    ('Stuttgart', 'node/1674026139', 'de'), ('Düsseldorf', 'node/240126753', 'de'),
    ('Dortmund', 'node/25293125', 'de'), ('Leipzig', 'node/21687149', 'de'),
    ('Bremen', 'node/20982927', 'de'), ('Dresden', 'node/20833613', 'de'),
    ('Nuremberg', 'node/1569338041', 'de'),
    ('Valencia', 'node/34105607', 'es'), ('Zaragoza', 'node/266776249', 'es'),
    ('Málaga', 'node/21750065', 'es'), ('Murcia', 'node/260380069', 'es'),
    ('Bilbao', 'node/27000762', 'es'), ('Granada', 'node/240423025', 'es'),
    ('Córdoba', 'node/21750062', 'es'),
    ('Turin', 'node/63621589', 'it'), ('Palermo', 'node/67253662', 'it'),
    ('Genoa', 'node/66586322', 'it'), ('Bologna', 'node/667350399', 'it'),
    ('Bari', 'node/68528585', 'it'), ('Verona', 'node/64778101', 'it'),
    ('Catania', 'node/67253693', 'it'),
    ('The Hague', 'node/235857686', 'nl'), ('Utrecht', 'node/235861650', 'nl'),
    ('Antwerp', 'node/1765433658', 'nl'),
    ('Wrocław', 'node/418392093', 'pl'), ('Gdańsk', 'node/26432122', 'pl'),
    ('Poznań', 'node/27161819', 'pl'), ('Łódź', 'node/30094969', 'pl'),
    ('Porto', 'node/2986300166', 'pt'),
    ('Thessaloniki', 'node/57554537', 'el'),
    ('Minsk', 'node/26162465', 'be'),
    ('Bratislava', 'node/530544342', 'sk'),
    ('Sarajevo', 'node/2021709163', 'bs'),
    ('Tirana', 'node/1835254686', 'sq'),
    ('Skopje', 'node/170792214', 'mk'),
    ('Chișinău', 'node/129991407', 'ro'),
    ('Pristina', 'node/2885136501', 'sq'),
    ('Podgorica', 'node/123860883', 'sr'),
    ('Gothenburg', 'node/25930131', 'sv'),
    ('Malmö', 'node/26804505', 'sv'),
)
LANGUAGES = ('zh', 'en', 'ja', 'fr', 'es')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path,
                        default=ROOT / 'work/osm-europe-cities/additional-50')
    args = parser.parse_args()
    if len(CITIES) != 50 or len({osm for _, osm, _ in CITIES}) != 50:
        raise ValueError('Expected 50 distinct OSM city nodes')
    source = json.loads((ROOT / 'work/osm-cities/cities.json').read_text(encoding='utf-8'))
    by_osm = {record['osm']: record for record in source}
    prior_files = (ROOT / 'work/osm-europe-cities/plan-45.json',
                   ROOT / 'work/osm-uk-cities/plan-30.json')
    previous = {item['osm'] for path in prior_files
                for item in json.loads(path.read_text(encoding='utf-8'))['selected']}
    settings = Settings.from_env()
    selected = []
    with connect(settings) as client:
        for label, osm, lang in CITIES:
            if osm in previous:
                raise ValueError(f'Already in earlier European batch: {label}')
            record = by_osm[osm]
            if record['kind'] != 'city':
                raise ValueError(f'Not a city: {label}')
            lon, lat = record['location']['lon'], record['location']['lat']
            if not (-26 < lon < 46 and 35 < lat < 72):
                raise ValueError(f'Outside Europe bounds: {label}')
            hits = client.search(index=settings.index,
                query={'term': {'external_ids.osm': osm}}, size=2)['hits']['hits']
            if len(hits) != 1:
                raise ValueError(f'Expected one ES document for {label}, got {len(hits)}')
            doc = hits[0]['_source']
            if doc['kind'] != 'city' or doc['feature_id'] != f'osm-{osm.replace("/", "-")}':
                raise ValueError(f'Unexpected ES identity for {label}')
            if doc.get('literal_name') or doc.get('literal_meanings'):
                raise ValueError(f'Already translated or pinned: {label}')
            local_name = record.get('names', {}).get(lang) or record['local_name']
            if local_name not in doc['names'].values():
                raise ValueError(f'Local name missing from ES: {label} / {local_name}')
            selected.append({'label': label, 'osm': osm, 'feature_id': doc['feature_id'],
                'population_osm': record.get('population'),
                'local_name': {'text': local_name, 'lang': lang},
                'needs_language_tag': doc['names'].get(lang) != local_name,
                'location': doc['location'], 'complete': False})
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / 'plan-50.json', {
        'created_at': timestamp(), 'index': settings.index,
        'rule': '50 further major European OSM city nodes, excluding previously processed Europe and UK batches',
        'selected': selected,
    })
    write_json(args.output_dir / 'feature-ids-50.json', [item['feature_id'] for item in selected])
    print(json.dumps({'selected': len(selected),
        'missing_local_language_tags': sum(item['needs_language_tag'] for item in selected)},
        ensure_ascii=False))


if __name__ == '__main__':
    main()
