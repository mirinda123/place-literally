"""Plan 30 more US cities from the already imported OSM city inventory."""

import argparse
import json
from pathlib import Path

from backend.config import ROOT, Settings, connect
from scripts.collect_osm_countries import timestamp, write_json


# IDs disambiguate namesakes such as Kansas City and Newark.
CITIES = (
    ('El Paso', 'node/50688894'), ('Memphis', 'node/151364154'),
    ('Louisville', 'node/153369793'), ('Baltimore', 'node/671113'),
    ('Milwaukee', 'node/873099231'), ('Albuquerque', 'node/151364049'),
    ('Tucson', 'node/150964034'), ('Fresno', 'node/1956099531'),
    ('Kansas City', 'node/1856296860'), ('Raleigh', 'node/158618991'),
    ('Sacramento', 'node/150959789'), ('Omaha', 'node/151499384'),
    ('Colorado Springs', 'node/151363387'), ('Buffalo', 'node/158230039'),
    ('Cleveland', 'node/18948478'), ('Virginia Beach', 'node/1979158327'),
    ('Orlando', 'node/99513584'), ('Oakland', 'node/150980683'),
    ('Tampa', 'node/153970120'), ('Tulsa', 'node/1917308451'),
    ('Pittsburgh', 'node/34184938'), ('Wichita', 'node/151817485'),
    ('Cincinnati', 'node/153938725'), ('Newark', 'node/158815316'),
    ('Saint Paul', 'node/151370941'), ('Honolulu', 'node/21442033'),
    ('Anchorage', 'node/150921144'), ('Salt Lake City', 'node/150935219'),
    ('Saint Louis', 'node/7504571159'), ('Baton Rouge', 'node/151904088'),
)
LANGUAGES = ('zh', 'en', 'ja', 'fr', 'es')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'work/osm-us-cities/additional-30')
    args = parser.parse_args()
    source = json.loads((ROOT / 'work/osm-cities/cities.json').read_text(encoding='utf-8'))
    by_osm = {record['osm']: record for record in source}
    prior = json.loads((ROOT / 'work/osm-us-cities/plan-30.json').read_text(encoding='utf-8'))
    prior_ids = {record['osm'] for record in prior['selected']}
    if len(CITIES) != 30 or len({osm for _, osm in CITIES}) != 30:
        raise ValueError('Expected 30 unique additional city nodes')
    settings = Settings.from_env()
    selected = []
    with connect(settings) as client:
        for label, osm in CITIES:
            if osm in prior_ids:
                raise ValueError(f'Already included in the prior US batch: {label}')
            record = by_osm[osm]
            if record['kind'] != 'city' or record.get('names', {}).get('en', record['local_name']) != label:
                raise ValueError(f'OSM label changed for {label}: {record}')
            hits = client.search(index=settings.index,
                query={'term': {'external_ids.osm': osm}}, size=2)['hits']['hits']
            if len(hits) != 1:
                raise ValueError(f'Expected one ES match for {label} / {osm}, found {len(hits)}')
            doc = hits[0]['_source']
            if doc['kind'] != 'city' or doc['feature_id'] != f'osm-{osm.replace("/", "-")}':
                raise ValueError(f'Unexpected ES identity for {label}')
            if doc['names'].get('en', doc['names'].get('und')) != label:
                raise ValueError(f'Unexpected English name for {label}: {doc["names"]}')
            meanings = doc.get('literal_meanings', [])
            complete = bool(meanings) and all(all(m['translations'].get(lang)
                for lang in LANGUAGES) for m in meanings)
            selected.append({
                'label': label, 'osm': osm, 'feature_id': doc['feature_id'],
                'population_osm': record.get('population'),
                'local_name': {'text': label, 'lang': 'en'},
                'needs_english_tag': 'en' not in doc['names'],
                'existing_literal_name': doc.get('literal_name'),
                'complete': complete, 'location': doc['location'],
            })
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / 'plan-30.json', {
        'created_at': timestamp(), 'index': settings.index,
        'rule': '30 additional major US OSM city nodes, explicitly disambiguated and excluding the first US city batch',
        'selected': selected,
    })
    write_json(args.output_dir / 'feature-ids-30.json', [item['feature_id'] for item in selected])
    print(json.dumps({
        'selected': len(selected), 'complete': sum(item['complete'] for item in selected),
        'pending': sum(not item['complete'] for item in selected),
        'missing_en_tags': sum(item['needs_english_tag'] for item in selected),
    }, ensure_ascii=True))


if __name__ == '__main__':
    main()
