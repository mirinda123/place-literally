"""Plan 30 further Chinese OSM city nodes for five-language meanings."""

import argparse
import json
from pathlib import Path

from backend.config import ROOT, Settings, connect
from scripts.collect_osm_countries import timestamp, write_json


# Explicit IDs keep homonymous cities and nearby districts out of the batch.
CITIES = (
    ('Harbin', 'node/279116876'),
    ('Taiyuan', 'node/244081765'),
    ('Hohhot', 'node/244080620'),
    ('Lhasa', 'node/31219396'),
    ('Kunming', 'node/3009802821'),
    ('Guiyang', 'node/244080395'),
    ('Haikou', 'node/244080519'),
    ('Lanzhou', 'node/4076799624'),
    ('Xining', 'node/244082386'),
    ('Yinchuan', 'node/244083626'),
    ('Ürümqi', 'node/244081999'),
    ('Kaohsiung', 'node/60655691'),
    ('Taichung', 'node/60655918'),
    ('Tainan', 'node/3014041771'),
    ('Foshan', 'node/244079402'),
    ('Wenzhou', 'node/244082236'),
    ('Weifang', 'node/4792682021'),
    ('Handan', 'node/244080536'),
    ('Xuzhou', 'node/4532193705'),
    ('Quanzhou', 'node/244081721'),
    ('Nantong', 'node/244081466'),
    ('Tangshan', 'node/244081797'),
    ('Wuxi', 'node/3073512713'),
    ('Yancheng', 'node/244082501'),
    ('Zunyi', 'node/244082552'),
    ('Shantou', 'node/8399236300'),
    ('Guilin', 'node/244080362'),
    ('Shaoxing', 'node/244081612'),
    ('Yangzhou', 'node/244082480'),
    ('Zhongshan', 'node/244083205'),
)
LANGUAGES = ('zh', 'en', 'ja', 'fr', 'es')


def choose_original(names, osm):
    order = ('zh-Hant', 'zh', 'zh-Hans') if osm in {
        'node/60655691', 'node/60655918', 'node/3014041771'
    } else ('zh-Hans', 'zh', 'zh-Hant')
    for lang in order:
        if names.get(lang):
            return {'text': names[lang], 'lang': lang}
    raise ValueError(f'Missing Chinese original for {osm}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path,
                        default=ROOT / 'work/osm-china-cities/additional-30')
    args = parser.parse_args()
    if len(CITIES) != 30 or len({osm for _, osm in CITIES}) != 30:
        raise ValueError('Expected 30 distinct OSM nodes')
    source = json.loads((ROOT / 'work/osm-cities/cities.json').read_text(encoding='utf-8'))
    by_osm = {record['osm']: record for record in source}
    previous = json.loads((ROOT / 'work/osm-china-cities/plan-30.json').read_text(encoding='utf-8'))
    previous_osm = {item['osm'] for item in previous['selected']}
    settings = Settings.from_env()
    selected = []
    with connect(settings) as client:
        for label, osm in CITIES:
            if osm in previous_osm:
                raise ValueError(f'Already in first China batch: {label}')
            record = by_osm[osm]
            if record['kind'] != 'city' or record['names'].get('en') != label:
                raise ValueError(f'Unexpected OSM city name for {label}: {record}')
            hits = client.search(index=settings.index,
                query={'term': {'external_ids.osm': osm}}, size=2)['hits']['hits']
            if len(hits) != 1:
                raise ValueError(f'Expected one ES document for {label}, got {len(hits)}')
            doc = hits[0]['_source']
            if doc['kind'] != 'city' or not doc['feature_id']:
                raise ValueError(f'Unexpected ES identity for {label}')
            original = choose_original(doc['names'], osm)
            meanings = doc.get('literal_meanings', [])
            complete = bool(meanings) and all(all(m['translations'].get(lang)
                for lang in LANGUAGES) for m in meanings)
            selected.append({
                'label': label, 'osm': osm, 'feature_id': doc['feature_id'],
                'population_osm': record.get('population'),
                'local_name': original, 'existing_literal_name': doc.get('literal_name'),
                'complete': complete, 'location': doc['location'],
            })
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / 'plan-30.json', {
        'created_at': timestamp(), 'index': settings.index,
        'rule': '30 additional prominent OSM place=city nodes across mainland China and Taiwan; explicit IDs avoid namesakes',
        'selected': selected,
    })
    write_json(args.output_dir / 'feature-ids-30.json',
               [item['feature_id'] for item in selected if not item['complete']])
    print(json.dumps({
        'selected': len(selected), 'complete': sum(item['complete'] for item in selected),
        'pending': sum(not item['complete'] for item in selected),
        'conflicting_originals': sum(bool(item['existing_literal_name']) and
            item['existing_literal_name'] != item['local_name'] for item in selected),
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
