"""Plan 50 untranslated African OSM cities across 22 country areas."""

import argparse
import json
from pathlib import Path

from backend.config import ROOT, Settings, connect
from scripts.collect_osm_countries import timestamp, write_json


# Population-weighted quotas give all five broad African regions coverage.
# Preferred tags identify a local spelling; they do not assert etymology.
QUOTAS = {
    'NG': (5, ('en',)), 'EG': (4, ('ar',)), 'ZA': (4, ('en', 'af')),
    'ET': (3, ('am',)), 'KE': (3, ('sw', 'en')),
    'MA': (3, ('ar', 'zgh')), 'DZ': (3, ('ar', 'fr')),
    'GH': (2, ('en',)), 'CI': (2, ('fr',)), 'SN': (2, ('fr',)),
    'TZ': (2, ('sw',)), 'UG': (2, ('en', 'sw')),
    'CD': (2, ('fr',)), 'AO': (2, ('pt',)), 'MZ': (2, ('pt',)),
    'CM': (2, ('fr', 'en')), 'SD': (2, ('ar',)),
    'TN': (1, ('ar',)), 'ZW': (1, ('en',)), 'ZM': (1, ('en',)),
    'MG': (1, ('mg', 'fr')), 'SO': (1, ('so',)),
}
LANGUAGES = ('zh', 'en', 'ja', 'fr', 'es')
# OSM population tags sometimes rank a satellite settlement above a capital
# or independent major city. These reviewed selections preserve geographic
# variety and avoid duplicate metropolitan areas.
PINNED_OSM = {
    'NG': ('node/27565124', 'node/27565066', 'node/501540880',
           'node/27565065', 'node/31203257'),
    'EG': ('node/271613766', 'node/27565020', 'node/27565120',
           'node/1667671370'),
    'ZA': ('node/261833893', 'node/32675806', 'node/27564996',
           'node/25470100'),
    'ET': ('node/27565076', 'node/298296168', 'node/71556493'),
    'DZ': ('node/299617915', 'node/27565103', 'node/27564946'),
    'UG': ('node/773119937', 'node/304816313'),
    'MZ': ('node/27565081', 'node/259593578'),
    'CM': ('node/732125487', 'node/331136682'),
    'TN': ('node/27564968',),
}
PRIMARY_NAME_EVIDENCE = {
    'node/27565008': 'https://cepici.gouv.ci/public/frontend/assets/document/investinbouake%2005%20JANVIER%202024%20sans%20pub%20update.pdf',
    'node/255590322': 'https://www.mwanzacc.go.tz/storage/app/uploads/public/5a0/98a/165/5a098a165f1e1020497705.pdf',
    'node/60715164': 'https://www.primature.gouv.cd/document/briefing-du-premier-ministre-jean-michel-sama-lukonde-kyenge-devant-la-presse-a-goma/',
    'node/279010461': 'https://benguela.gov.ao/web/noticias/benguela-e-lobito-acolhem-o-lancamento-de-obras-literarias-de-paula-russa-e-jose-pires-bongue',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cities', type=Path,
                        default=ROOT / 'work/osm-africa-cities/cities.json')
    parser.add_argument('--output-dir', type=Path,
                        default=ROOT / 'work/osm-africa-cities/selected-50')
    args = parser.parse_args()
    if sum(count for count, _ in QUOTAS.values()) != 50:
        raise ValueError('The Africa quotas must total 50')
    cities = json.loads(args.cities.read_text(encoding='utf-8'))
    if {scope for item in cities for scope in item['query_scopes']} != set(QUOTAS):
        raise ValueError('Country-scoped OSM source is missing or has unexpected countries')
    settings = Settings.from_env()
    selected, skipped = [], {}
    with connect(settings) as client:
        for country, (quota, preferences) in QUOTAS.items():
            candidates = sorted(
                (item for item in cities if item['kind'] == 'city'
                 and country in item['query_scopes']),
                key=lambda item: (item.get('population') or 0,
                                  item['osm']), reverse=True)
            if country in PINNED_OSM:
                pinned = PINNED_OSM[country]
                by_osm = {item['osm']: item for item in candidates}
                if len(pinned) != quota or any(osm not in by_osm for osm in pinned):
                    raise ValueError(f'{country} pinned OSM city selection is stale')
                candidates = [by_osm[osm] for osm in pinned]
            picks = []
            for item in candidates:
                if len(picks) == quota:
                    break
                osm = item['osm']
                hits = client.search(index=settings.index,
                                     query={'term': {'external_ids.osm': osm}},
                                     size=2)['hits']['hits']
                if len(hits) != 1:
                    skipped[osm] = f'{len(hits)} ES matches'
                    continue
                doc = hits[0]['_source']
                if (doc['kind'] != 'city' or
                        doc['feature_id'] != f'osm-{osm.replace("/", "-")}' or
                        osm not in doc.get('external_ids', {}).get('osm', [])):
                    raise ValueError(f'Unexpected ES identity for {osm}')
                if doc.get('literal_name') or doc.get('literal_meanings'):
                    skipped[osm] = 'already pinned or translated'
                    continue
                choices = [(lang, item['names'][lang]) for lang in preferences
                           if item['names'].get(lang)]
                if choices:
                    lang, original = choices[0]
                    source = f'name:{lang}'
                else:
                    lang, original = preferences[0], item.get('local_name')
                    source = 'name'
                    if osm not in PRIMARY_NAME_EVIDENCE:
                        skipped[osm] = 'unreviewed primary name language'
                        continue
                if not original or original not in doc.get('names', {}).values():
                    skipped[osm] = 'no ES-attested local spelling'
                    continue
                pick = {'label': item['names'].get('en') or item['local_name'],
                        'country': country, 'osm': osm,
                        'feature_id': doc['feature_id'], 'kind': 'city',
                        'local_name': {'text': original, 'lang': lang},
                        'original_source_tag': source,
                        'primary_name_evidence': PRIMARY_NAME_EVIDENCE.get(osm),
                        'needs_language_tag': doc['names'].get(lang) != original,
                        'location': doc['location'],
                        'population_osm': item.get('population')}
                picks.append(pick)
                selected.append(pick)
            if len(picks) != quota:
                raise ValueError(f'{country} has {len(picks)} eligible cities, expected {quota}')
    if len(selected) != 50 or len({item['osm'] for item in selected}) != 50:
        raise ValueError('Expected 50 unique OSM city nodes')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / 'plan-50.json', {
        'created_at': timestamp(), 'index': settings.index,
        'rule': '50 untranslated major OSM cities across 22 African countries',
        'quota_by_country': {key: count for key, (count, _) in QUOTAS.items()},
        'languages': LANGUAGES, 'selected': selected, 'skipped': skipped,
        'review_notice': 'Each name sourced only from OSM name tags; verify every language and local spelling before applying.',
    })
    write_json(args.output_dir / 'feature-ids-50.json',
               [item['feature_id'] for item in selected])
    print(json.dumps({'index': settings.index, 'selected': len(selected),
                      'countries': len(QUOTAS),
                      'primary_name_fallbacks': sum(item['original_source_tag'] == 'name'
                                                    for item in selected),
                      'output': str(args.output_dir.resolve())}, ensure_ascii=True))


if __name__ == '__main__':
    main()
