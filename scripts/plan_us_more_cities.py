"""Plan 50 further US OSM cities without reusing earlier batches."""

import argparse
import json
from pathlib import Path

from backend.config import ROOT, Settings, connect
from scripts.collect_osm_countries import timestamp, write_json


# Labels and OSM nodes are curated together; duplicated city names include a state.
CITIES = (
    ('Mesa', 'node/150966739'), ('Long Beach', 'node/6474240715'),
    ('Bakersfield', 'node/1979182884'), ('Aurora, Colorado', 'node/151744721'),
    ('Arlington, Texas', 'node/151555783'), ('Anaheim', 'node/1837296118'),
    ('Henderson', 'node/150950536'), ('Santa Ana', 'node/1837289829'),
    ('Lexington', 'node/154320458'), ('Riverside', 'node/150935360'),
    ('Corpus Christi', 'node/151664734'), ('Greensboro', 'node/158417274'),
    ('Stockton', 'node/150963006'), ('North Las Vegas', 'node/150969163'),
    ('Jersey City', 'node/158840157'), ('Lincoln', 'node/151467659'),
    ('Plano', 'node/1513101697'), ('Reno', 'node/150959273'),
    ('Durham', 'node/158605665'), ('Chandler', 'node/608510493'),
    ('Gilbert', 'node/150937821'), ('Chula Vista', 'node/150981937'),
    ('Toledo', 'node/18954801'), ('Madison', 'node/29941752'),
    ('Lubbock', 'node/151367745'), ('Glendale, Arizona', 'node/150969901'),
    ('Irvine', 'node/1837177146'), ('Irving', 'node/4400006133'),
    ('Chesapeake', 'node/158556083'), ('Laredo', 'node/8626728781'),
    ('Winston-Salem', 'node/153905024'), ('Fort Wayne', 'node/153744573'),
    ('Scottsdale', 'node/150953270'), ('Saint Petersburg, Florida', 'node/154143132'),
    ('Garland', 'node/151836509'), ('Fremont', 'node/150950777'),
    ('Boise', 'node/59900417'), ('Norfolk', 'node/2933637976'),
    ('Spokane', 'node/48925897'), ('Richmond, Virginia', 'node/2592301390'),
    ('Hialeah', 'node/154063226'), ('San Bernardino', 'node/150958886'),
    ('Tacoma', 'node/256170687'), ('Huntsville', 'node/153386290'),
    ('Des Moines', 'node/125027380'), ('Yonkers', 'node/158846316'),
    ('Rochester, New York', 'node/1517267225'), ('Modesto', 'node/150938628'),
    ('Frisco', 'node/151578627'), ('Oxnard', 'node/150942402'),
)
LANGUAGES = ('zh', 'en', 'ja', 'fr', 'es')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path,
                        default=ROOT / 'work/osm-us-cities/additional-50')
    args = parser.parse_args()
    if len(CITIES) != 50 or len({osm for _, osm in CITIES}) != 50:
        raise ValueError('Expected 50 distinct US OSM city nodes')
    source = json.loads((ROOT / 'work/osm-cities/cities.json').read_text(encoding='utf-8'))
    by_osm = {record['osm']: record for record in source}
    prior_files = (ROOT / 'work/osm-us-cities/plan-30.json',
                   ROOT / 'work/osm-us-cities/additional-30/plan-30.json')
    previous = {item['osm'] for path in prior_files
                for item in json.loads(path.read_text(encoding='utf-8'))['selected']}
    settings = Settings.from_env()
    selected = []
    with connect(settings) as client:
        for label, osm in CITIES:
            if osm in previous:
                raise ValueError(f'Already in earlier US batch: {label}')
            record = by_osm[osm]
            english = record.get('names', {}).get('en', record['local_name'])
            if record['kind'] != 'city' or english != label.split(', ')[0]:
                raise ValueError(f'Unexpected OSM city name for {label}: {record}')
            hits = client.search(index=settings.index,
                query={'term': {'external_ids.osm': osm}}, size=2)['hits']['hits']
            if len(hits) != 1:
                raise ValueError(f'Expected one ES document for {label}, got {len(hits)}')
            doc = hits[0]['_source']
            if doc['kind'] != 'city' or doc['feature_id'] != f'osm-{osm.replace("/", "-")}':
                raise ValueError(f'Unexpected ES identity for {label}')
            if doc.get('literal_name') or doc.get('literal_meanings'):
                raise ValueError(f'Already translated or pinned: {label}')
            selected.append({'label': label, 'osm': osm, 'feature_id': doc['feature_id'],
                'population_osm': record.get('population'),
                'local_name': {'text': english, 'lang': 'en'},
                'needs_english_tag': 'en' not in doc['names'],
                'location': doc['location'], 'complete': False})
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / 'plan-50.json', {
        'created_at': timestamp(), 'index': settings.index,
        'rule': '50 further prominent US OSM place=city nodes; explicit IDs disambiguate namesakes',
        'selected': selected,
    })
    write_json(args.output_dir / 'feature-ids-50.json', [item['feature_id'] for item in selected])
    print(json.dumps({'selected': len(selected),
        'missing_en_tags': sum(item['needs_english_tag'] for item in selected)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
