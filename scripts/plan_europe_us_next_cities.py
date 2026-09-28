"""Plan another 50 Europe or US cities with explicit, non-reused OSM IDs."""

import argparse
import json
from pathlib import Path

from backend.config import ROOT, Settings, connect
from scripts.collect_osm_countries import timestamp, write_json


# Each OSM ID is bound to a reviewed city label; namesakes cannot be selected
# by population or by a mutable English display name.
EUROPE = (
    ('Montpellier', 'node/65442261', 'fr'), ('Rennes', 'node/26686526', 'fr'),
    ('Reims', 'node/26686477', 'fr'), ('Le Havre', 'node/1909836591', 'fr'),
    ('Grenoble', 'node/26686589', 'fr'), ('Dijon', 'node/26686504', 'fr'),
    ('Angers', 'node/26686572', 'fr'), ('Brest, France', 'node/823582966', 'fr'),
    ('Rouen', 'node/26686587', 'fr'), ('Saint-Étienne', 'node/26686539', 'fr'),
    ('Essen', 'node/27350363', 'de'), ('Hanover', 'node/1651888734', 'de'),
    ('Duisburg', 'node/240055326', 'de'), ('Bochum', 'node/240099833', 'de'),
    ('Wuppertal', 'node/240090728', 'de'), ('Bonn', 'node/26373169', 'de'),
    ('Bielefeld', 'node/240037709', 'de'), ('Münster', 'node/273510436', 'de'),
    ('Mannheim', 'node/240060919', 'de'), ('Augsburg', 'node/1559853166', 'de'),
    ('Wiesbaden', 'node/240028377', 'de'), ('Karlsruhe', 'node/240120582', 'de'),
    ('Valladolid', 'node/29272534', 'es'), ('Palma', 'node/289643197', 'es'),
    ('Gijón', 'node/529391484', 'es'), ('Vitoria-Gasteiz', 'node/27000791', 'es'),
    ('Padua', 'node/406747508', 'it'), ('Trieste', 'node/66502648', 'it'),
    ('Brescia', 'node/62505590', 'it'), ('Taranto', 'node/68528603', 'it'),
    ('Parma', 'node/69300007', 'it'), ('Modena', 'node/69300003', 'it'),
    ('Livorno', 'node/1697770807', 'it'),
    ('Szczecin', 'node/26553042', 'pl'), ('Lublin', 'node/30014556', 'pl'),
    ('Bydgoszcz', 'node/31337673', 'pl'), ('Białystok', 'node/60038888', 'pl'),
    ('Gdynia', 'node/26432430', 'pl'),
    ('Brno', 'node/1601566699', 'cs'), ('Ostrava', 'node/1601523251', 'cs'),
    ('Graz', 'node/21015489', 'de'), ('Cluj-Napoca', 'node/32591050', 'ro'),
    ('Timișoara', 'node/57116400', 'ro'), ('Kaunas', 'node/27193090', 'lt'),
    ('Bergen', 'node/21261083', 'no'), ('Aarhus', 'node/26559213', 'da'),
    ('Tampere', 'node/30969480', 'fi'), ('Novi Sad', 'node/59735022', 'sr'),
    ('Ghent', 'node/1668655163', 'nl'), ('Patras', 'node/62221032', 'el'),
)

US = (
    ('Worcester, MA', 'node/158851900'), ('Fayetteville, NC', 'node/157562069'),
    ('Peoria, AZ', 'node/1340670207'), ('McKinney, TX', 'node/26454871'),
    ('Little Rock, AR', 'node/151470742'), ('Augusta, GA', 'node/154335770'),
    ('Glendale, CA', 'node/1785584728'), ('Birmingham, AL', 'node/153466590'),
    ('Montgomery, AL', 'node/153806548'), ('Amarillo, TX', 'node/11878503248'),
    ('Grand Rapids, MI', 'node/153348187'), ('Overland Park, KS', 'node/151422010'),
    ('Tallahassee, FL', 'node/154051410'), ('Fontana, CA', 'node/150955222'),
    ('Huntington Beach, CA', 'node/876627764'), ('Tempe, AZ', 'node/150937357'),
    ('Sioux Falls, SD', 'node/151734278'), ('Vancouver, WA', 'node/48723103'),
    ('Knoxville, TN', 'node/1979205040'), ('Akron, OH', 'node/153847849'),
    ('Shreveport, LA', 'node/29405948'), ('Mobile, AL', 'node/153638526'),
    ('Brownsville, TX', 'node/151629400'), ('Cary, NC', 'node/361424182'),
    ('Moreno Valley, CA', 'node/150940343'), ('Grand Prairie, TX', 'node/151859897'),
    ('Newport News, VA', 'node/317004626'), ('Santa Clarita, CA', 'node/150973333'),
    ('Clarksville, TN', 'node/34692633'), ('Aurora, IL', 'node/153812116'),
    ('Providence, RI', 'node/158811904'), ('Chattanooga, TN', 'node/153458138'),
    ('Santa Rosa, CA', 'node/150934574'), ('Oceanside, CA', 'node/150946956'),
    ('Ontario, CA', 'node/150965235'), ('Garden Grove, CA', 'node/1837289828'),
    ('Rancho Cucamonga, CA', 'node/150936096'), ('Springfield, MO', 'node/151340686'),
    ('Surprise, AZ', 'node/150971258'), ('Elk Grove, CA', 'node/150968654'),
    ('Fort Lauderdale, FL', 'node/154017676'), ('Port Saint Lucie, FL', 'node/154194802'),
    ('Alexandria, VA', 'node/1979420355'), ('Hayward, CA', 'node/150964675'),
    ('Eugene, OR', 'node/904722443'), ('Charleston, SC', 'node/36967884'),
    ('Salinas, CA', 'node/1684098883'), ('Dayton, OH', 'node/154381880'),
    ('Salem, OR', 'node/150956539'), ('Cape Coral, FL', 'node/154286316'),
)

PREVIOUS = {
    'europe': ('work/osm-europe-cities/plan-45.json',
               'work/osm-europe-cities/additional-50/plan-50.json',
               'work/osm-uk-cities/plan-30.json'),
    'us': ('work/osm-us-cities/plan-30.json',
           'work/osm-us-cities/additional-30/plan-30.json',
           'work/osm-us-cities/additional-50/plan-50.json'),
}

# The primary OSM name is identical to the local spelling, but these five
# nodes lack a dedicated name:<language> tag. The language is corroborated by
# the source's local-language article or by the city's own site.
PRIMARY_FALLBACKS = {
    'node/26686589': ('fr', 'Grenoble', 'https://fr.wikipedia.org/wiki/Grenoble'),
    'node/240099833': ('de', 'Bochum', 'https://de.wikipedia.org/wiki/Bochum'),
    'node/240120582': ('de', 'Karlsruhe', 'https://www.karlsruhe.de/'),
    'node/1697770807': ('it', 'Livorno', 'https://it.wikipedia.org/wiki/Livorno'),
    'node/21261083': ('no', 'Bergen', 'https://no.wikipedia.org/wiki/Bergen'),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('region', choices=('europe', 'us'))
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    entries = EUROPE if args.region == 'europe' else US
    if len(entries) != 50 or len({row[1] for row in entries}) != 50:
        raise ValueError('Expected 50 unique OSM nodes')
    old = {item['osm'] for path in PREVIOUS[args.region]
           for item in json.loads((ROOT / path).read_text(encoding='utf-8'))['selected']}
    cities = json.loads((ROOT / 'work/osm-cities/cities.json').read_text(encoding='utf-8'))
    by_osm = {item['osm']: item for item in cities}
    raw = json.loads((ROOT / 'work/osm-cities/global-cities-50000.raw.json').read_text(encoding='utf-8'))
    tags_by_osm = {f"node/{item['id']}": item.get('tags', {})
                   for item in raw['response']['elements'] if item.get('type') == 'node'}
    settings = Settings.from_env()
    selected = []
    with connect(settings) as client:
        for row in entries:
            label, osm = row[:2]
            if osm in old:
                raise ValueError(f'Previously selected: {label} ({osm})')
            source = by_osm[osm]
            if source['kind'] != 'city':
                raise ValueError(f'Not a city: {label}')
            tags = tags_by_osm[osm]
            if args.region == 'us':
                if not tags.get('gnis:feature_id') and not tags.get('website'):
                    raise ValueError(f'No US GNIS or municipal-site evidence: {label}')
                language = 'en'
            else:
                language = row[2]
            local = source['names'].get(language)
            evidence = None
            if not local and osm in PRIMARY_FALLBACKS:
                fallback_lang, fallback_text, evidence = PRIMARY_FALLBACKS[osm]
                if (language != fallback_lang or source['local_name'] != fallback_text
                        or tags.get('name') != fallback_text):
                    raise ValueError(f'Primary OSM name changed: {label}')
                local = fallback_text
            if not local:
                raise ValueError(f'Missing locally attested name:{language}: {label}')
            hits = client.search(index=settings.index,
                query={'term': {'external_ids.osm': osm}}, size=2)['hits']['hits']
            if len(hits) != 1:
                raise ValueError(f'Expected one ES match for {label}: {len(hits)}')
            doc = hits[0]['_source']
            if (doc['feature_id'] != f'osm-{osm.replace("/", "-")}' or
                    doc['kind'] != 'city' or osm not in doc['external_ids']['osm']):
                raise ValueError(f'Unexpected ES identity for {label}')
            if doc.get('literal_name') or doc.get('literal_meanings'):
                raise ValueError(f'Already pinned or translated: {label}')
            if local not in doc['names'].values():
                raise ValueError(f'Original spelling missing from ES: {label}')
            selected.append({'label': label, 'osm': osm, 'feature_id': doc['feature_id'],
                'kind': 'city', 'local_name': {'text': local, 'lang': language},
                'original_source_tag': f'name:{language}' if not evidence else 'name',
                'primary_name_evidence': evidence,
                'country_evidence': (tags.get('gnis:feature_id') or tags.get('website'))
                    if args.region == 'us' else None,
                'needs_language_tag': doc['names'].get(language) != local,
                'population_osm': source.get('population'), 'location': doc['location']})
    out = args.output_dir or ROOT / f'work/osm-{args.region}-cities/third-50'
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / 'plan-50.json', {'created_at': timestamp(), 'index': settings.index,
        'rule': f'50 further distinct {args.region} OSM city nodes; prior batches excluded',
        'languages': ('zh', 'en', 'ja', 'fr', 'es'), 'selected': selected})
    write_json(out / 'feature-ids-50.json', [item['feature_id'] for item in selected])
    print(json.dumps({'region': args.region, 'selected': len(selected),
        'needs_language_tag': sum(item['needs_language_tag'] for item in selected),
        'output': str(out.resolve())}, ensure_ascii=True))


if __name__ == '__main__':
    main()
