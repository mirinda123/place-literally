"""Select 49 major Indian cities and 31 OSM region labels for translation."""

import argparse
import json
from pathlib import Path

from backend.config import ROOT, Settings, connect
from scripts.collect_osm_countries import timestamp, write_json

CITY_LANGS = {
    'Delhi': 'hi', 'Mumbai': 'mr', 'Bengaluru': 'kn', 'Surat': 'gu',
    'Hyderabad': 'te', 'Ahmedabad': 'gu', 'Prayagraj': 'hi', 'Chennai': 'ta',
    'Lucknow': 'hi', 'Kolkata': 'bn', 'Indore': 'hi', 'Pune': 'mr',
    'Varanasi': 'hi', 'Jaipur': 'hi', 'Kanpur': 'hi', 'Visakhapatnam': 'te',
    'Nagpur': 'mr', 'Ludhiana': 'pa', 'Thane': 'mr', 'Bhopal': 'hi',
    'Pimpri-Chinchwad': 'mr', 'Ghaziabad': 'hi', 'Madurai': 'ta',
    'Siliguri': 'bn', 'Agra': 'hi', 'Nashik': 'mr', 'Kurukshetra': 'hi',
    'Bhubaneshwar': 'or', 'Meerut': 'hi', 'Rajkot': 'gu',
    'Kalyan-Dombivli': 'mr', 'Vasai-Virar': 'mr', 'Srinagar': 'ks',
    'Chhatrapati Sambhajinagar': 'mr', 'Dhanbad': 'hi', 'Amritsar': 'pa',
    'Navi Mumbai': 'mr', 'Ranchi': 'hi', 'Howrah': 'bn',
    'Coimbatore': 'ta', 'Vijayawada': 'te', 'Jodhpur': 'hi',
    'Chandigarh': 'pa', 'Raipur': 'hi', 'Kota': 'hi', 'Guwahati': 'en',
    'Solapur': 'mr', 'Jalandhar': 'pa', 'Rewari': 'hi',
}
REGION_LANGS = {
    'Andaman and Nicobar Islands': 'en', 'Andhra Pradesh': 'te',
    'Arunachal Pradesh': 'en', 'Assam': 'as', 'Bihar': 'hi',
    'Chhattisgarh': 'hi', 'Delhi': 'hi', 'Goa': 'kok', 'Gujarat': 'gu',
    'Haryana': 'hi', 'Himachal Pradesh': 'hi', 'Jammu and Kashmir': 'en',
    'Jharkhand': 'hi', 'Karnataka': 'kn', 'Kerala': 'ml', 'Ladakh': 'en',
    'Madhya Pradesh': 'hi', 'Maharashtra': 'mr', 'Manipur': 'en',
    'Meghalaya': 'en', 'Mizoram': 'en', 'Nagaland': 'en',
    'Odisha': 'or', 'Punjab': 'pa', 'Rajasthan': 'hi',
    'Tamil Nadu': 'ta', 'Telangana': 'te', 'Tripura': 'bn',
    'Uttar Pradesh': 'hi', 'Uttarakhand': 'hi', 'West Bengal': 'bn',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cities', type=Path, default=ROOT / 'work/osm-india-cities/cities.json')
    parser.add_argument('--regions', type=Path, default=ROOT / 'work/osm-india-regions/regions.json')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'work/osm-india-places')
    args = parser.parse_args()
    cities = json.loads(args.cities.read_text(encoding='utf-8'))
    regions = json.loads(args.regions.read_text(encoding='utf-8'))
    top_cities = sorted((item for item in cities if item['kind'] == 'city'),
                        key=lambda item: item.get('population') or 0, reverse=True)[:49]
    city_labels = [item['names'].get('en') or item['local_name'] for item in top_cities]
    region_labels = [item['short_label'] for item in regions]
    if (len(top_cities) != 49 or len(regions) != 31 or len(set(city_labels)) != 49
            or set(city_labels) != set(CITY_LANGS) or set(region_labels) != set(REGION_LANGS)):
        raise ValueError('Cached Indian city or region selection differs from the reviewed 80 names')
    sources = [(item, label, CITY_LANGS[label], 'city')
               for item, label in zip(top_cities, city_labels)]
    sources += [(item, item['short_label'], REGION_LANGS[item['short_label']], 'state')
                for item in regions]
    if len({item['osm'] for item, _, _, _ in sources}) != 80:
        raise ValueError('OSM identifiers are not unique')
    settings = Settings.from_env()
    selected = []
    with connect(settings) as client:
        for item, label, lang, kind in sources:
            original = item['names'].get(lang)
            if not original or not original.strip():
                raise ValueError(f'Missing attested {lang} spelling for {label}')
            osm = item['osm']
            hits = client.search(index=settings.index, query={'term': {'external_ids.osm': osm}},
                                 size=2)['hits']['hits']
            if len(hits) != 1:
                raise ValueError(f'Expected one ES feature for {label} ({osm}), got {len(hits)}')
            doc = hits[0]['_source']
            if (doc['kind'] != kind or doc['feature_id'] != f'osm-{osm.replace("/", "-")}'
                    or osm not in doc.get('external_ids', {}).get('osm', [])):
                raise ValueError(f'Unexpected ES identity for {label} ({osm})')
            if doc.get('literal_meanings'):
                raise ValueError(f'Already translated; choose another target: {label}')
            local_name = {'text': original, 'lang': lang}
            if doc.get('literal_name') and doc['literal_name'] != local_name:
                raise ValueError(f'Existing original differs for {label}')
            selected.append({'label': label, 'osm': osm, 'feature_id': doc['feature_id'],
                             'kind': kind, 'local_name': local_name,
                             'location': doc['location'],
                             'population_osm': item.get('population'),
                             'category': 'city' if kind == 'city' else item['category']})
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / 'plan-80.json', {
        'created_at': timestamp(), 'index': settings.index,
        'rule': '49 largest cached OSM place=city nodes within India, plus 31 locally attested state/UT place nodes; no existing meanings',
        'languages': ['zh', 'en', 'ja', 'fr', 'es'], 'selected': selected,
    })
    write_json(args.output_dir / 'feature-ids-80.json', [item['feature_id'] for item in selected])
    print(json.dumps({'index': settings.index, 'cities': 49, 'regions': 31,
                      'selected': len(selected), 'output': str(args.output_dir.resolve())},
                     ensure_ascii=True))


if __name__ == '__main__':
    main()
