"""Plan 50 additional Chinese OSM city nodes for five-language meanings."""

import argparse
import json
from pathlib import Path

from backend.config import ROOT, Settings, connect
from scripts.collect_osm_countries import timestamp, write_json


# Explicit nodes prevent a population sort from selecting foreign cities,
# administrative districts, or another place with the same name.
CITIES = (
    ('Zhoukou', 'node/244083185'), ('Heze', 'node/244080640'),
    ('Jining', 'node/244080792'), ('Fuyang', 'node/244079835'),
    ('Yulin', 'node/244082760'), ('Cangzhou', 'node/244076965'),
    ('Shaoyang', 'node/244081610'), ('Bijie', 'node/3006138874'),
    ('Shangrao', 'node/244081672'), ('Huanggang', 'node/244080695'),
    ('Jieyang', 'node/2703828665'), ('Qujing', 'node/469624375'),
    ('Changde', 'node/244076990'), ('Xinxiang', 'node/244082431'),
    ('Dezhou', 'node/244078533'), ('Nanchong', 'node/244081437'),
    ('Xiangyang', 'node/244082143'), ('Yichun', 'node/244082250'),
    ('Suihua', 'node/244081815'), ('Qiqihar', 'node/244081515'),
    ('Jinhua', 'node/244080787'), ('Suzhou', 'node/244081835'),
    ('Yuncheng', 'node/244082765'), ('Changzhou', 'node/244077447'),
    ('Yongzhou', 'node/244081152'), ('Zhaotong', 'node/418286525'),
    ('Pingdingshan', 'node/244081348'), ('Mianyang', 'node/244081207'),
    ('Xiaogan', 'node/244082129'), ("Ji'an", 'node/244080755'),
    ('Zhangzhou', 'node/244082898'), ("Huai'an", 'node/244080563'),
    ('Huaihua', 'node/244080571'), ('Jiujiang', 'node/244080937'),
    ('Suqian', 'node/244081833'), ('Weinan', 'node/244081932'),
    ('Kaifeng', 'node/244080911'), ('Chenzhou', 'node/244077521'),
    ('Huizhou', 'node/244080677'), ('Yibin', 'node/244082258'),
    ('Taizhou', 'node/244081796'), ('Jiangmen', 'node/369500555'),
    ('Hengshui', 'node/244080601'), ('Lianyungang', 'node/244081108'),
    ("Lu'an", 'node/244081239'), ('Zhangjiakou', 'node/244082892'),
    ('Yiyang', 'node/244082340'), ('Xuchang', 'node/244082443'),
    ('Luzhou', 'node/244081288'), ('New Taipei', 'node/60655699'),
)
LANGUAGES = ('zh', 'en', 'ja', 'fr', 'es')


def choose_original(names, osm):
    order = ('zh-Hant', 'zh', 'zh-Hans') if osm == 'node/60655699' else ('zh-Hans', 'zh', 'zh-Hant')
    for lang in order:
        if names.get(lang):
            return {'text': names[lang], 'lang': lang}
    raise ValueError(f'Missing Chinese original for {osm}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path,
                        default=ROOT / 'work/osm-china-cities/additional-50')
    args = parser.parse_args()
    if len(CITIES) != 50 or len({osm for _, osm in CITIES}) != 50:
        raise ValueError('Expected 50 distinct OSM nodes')
    source = json.loads((ROOT / 'work/osm-cities/cities.json').read_text(encoding='utf-8'))
    by_osm = {record['osm']: record for record in source}
    prior_files = (ROOT / 'work/osm-china-cities/plan-30.json',
                   ROOT / 'work/osm-china-cities/additional-30/plan-30.json')
    previous_osm = {item['osm'] for path in prior_files
                    for item in json.loads(path.read_text(encoding='utf-8'))['selected']}
    settings = Settings.from_env()
    selected = []
    with connect(settings) as client:
        for label, osm in CITIES:
            if osm in previous_osm:
                raise ValueError(f'Already in earlier China batch: {label}')
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
            if meanings or doc.get('literal_name'):
                raise ValueError(f'Already translated or pinned: {label}')
            selected.append({
                'label': label, 'osm': osm, 'feature_id': doc['feature_id'],
                'population_osm': record.get('population'),
                'local_name': original, 'existing_literal_name': None,
                'complete': complete, 'location': doc['location'],
            })
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / 'plan-50.json', {
        'created_at': timestamp(), 'index': settings.index,
        'rule': '50 further prominent OSM place=city nodes across mainland China and Taiwan; explicit IDs avoid namesakes',
        'selected': selected,
    })
    write_json(args.output_dir / 'feature-ids-50.json',
               [item['feature_id'] for item in selected if not item['complete']])
    print(json.dumps({'selected': len(selected), 'pending': sum(not item['complete'] for item in selected)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
