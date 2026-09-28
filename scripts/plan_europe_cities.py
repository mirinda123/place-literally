"""Plan a multilingual literal-name batch for 45 prominent European city labels."""

import argparse
import json
from pathlib import Path

from backend.config import ROOT, Settings, connect
from scripts.collect_osm_countries import timestamp, write_json

# Curated major capitals and regional centres, including European portions of
# Russia and Turkey. Values are the locally used OSM language tag to explain.
CITIES = (
    ('London', 'en'), ('Paris', 'fr'), ('Berlin', 'de'), ('Madrid', 'es'),
    ('Rome', 'it'), ('Moscow', 'ru'), ('Istanbul', 'tr'), ('Amsterdam', 'nl'),
    ('Brussels', 'nl'), ('Vienna', 'de'), ('Prague', 'cs'), ('Warsaw', 'pl'),
    ('Budapest', 'hu'), ('Lisbon', 'pt'), ('Dublin', 'en'), ('Copenhagen', 'da'),
    ('Stockholm', 'sv'), ('Oslo', 'no'), ('Helsinki', 'fi'), ('Athens', 'el'),
    ('Kyiv', 'uk'), ('Bucharest', 'ro'), ('Zurich', 'de'), ('Milan', 'it'),
    ('Barcelona', 'ca'), ('Munich', 'de'), ('Hamburg', 'de'),
    ('Saint Petersburg', 'ru'), ('Edinburgh', 'en'), ('Naples', 'it'),
    ('Venice', 'it'), ('Florence', 'it'), ('Seville', 'es'),
    ('Rotterdam', 'nl'), ('Krakow', 'pl'), ('Belgrade', 'sr'),
    ('Sofia', 'bg'), ('Zagreb', 'hr'), ('Tallinn', 'et'),
    ('Reykjavik', 'is'), ('Riga', 'lv'), ('Vilnius', 'lt'),
    ('Ljubljana', 'sl'), ('Luxembourg', 'lb'), ('Geneva', 'fr'),
)
LANGUAGES = ('zh', 'en', 'ja', 'fr', 'es')


def choose(cities, label):
    candidates = [city for city in cities
                  if city.get('names', {}).get('en') == label or city.get('local_name') == label]
    candidates = [city for city in candidates if
                  -26 < city['location']['lon'] < 46 and 35 < city['location']['lat'] < 72]
    if not candidates:
        raise ValueError(f'Missing European OSM city label: {label}')
    return max(candidates, key=lambda city: city.get('population') or 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'work/osm-europe-cities')
    args = parser.parse_args()
    cities = json.loads((ROOT / 'work/osm-cities/cities.json').read_text(encoding='utf-8'))
    settings = Settings.from_env()
    selected = []
    with connect(settings) as client:
        for label, local_lang in CITIES:
            record = choose(cities, label)
            hits = client.search(index=settings.index, query={'term': {'external_ids.osm': record['osm']}}, size=2)['hits']['hits']
            if len(hits) != 1:
                raise ValueError(f'Expected one ES match for {label} / {record["osm"]}, found {len(hits)}')
            doc = hits[0]['_source']
            if doc['kind'] != 'city':
                raise ValueError(f'Not a city: {label} / {doc["kind"]}')
            local_name = doc['names'].get(local_lang)
            if not local_name or local_name != record['names'].get(local_lang):
                raise ValueError(f'Expected OSM {local_lang} name for {label}')
            meanings = doc.get('literal_meanings', [])
            complete = bool(meanings) and all(all(m['translations'].get(lang)
                for lang in LANGUAGES) for m in meanings)
            selected.append({'label': label, 'osm': record['osm'], 'feature_id': doc['feature_id'],
                             'population_osm': record.get('population'),
                             'local_name': {'text': local_name, 'lang': local_lang},
                             'existing_literal_name': doc.get('literal_name'),
                             'complete': complete, 'location': doc['location']})
    if len(selected) != len({item['osm'] for item in selected}) or len(selected) != 45:
        raise ValueError('Expected 45 distinct city labels')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    plan = {'created_at': timestamp(), 'index': settings.index,
            'rule': '45 curated major European city labels; choose unique OSM node and pin its locally attested name before translation',
            'selected': selected}
    write_json(args.output_dir / 'plan-45.json', plan)
    write_json(args.output_dir / 'feature-ids-45.json', [item['feature_id'] for item in selected])
    print(json.dumps({'selected': len(selected), 'complete': sum(item['complete'] for item in selected),
                      'pending': sum(not item['complete'] for item in selected)}, ensure_ascii=True))


if __name__ == '__main__':
    main()
