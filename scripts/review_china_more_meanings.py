"""Correct documented mismatches between a city-name draft and its sources."""

import argparse
from datetime import datetime, timezone
import json

from backend.config import ROOT, Settings, connect
from backend.indexing import Feature


OUTPUT_ROOT = ROOT / 'work/literal-translations/china-more-cities-20260927'
CORRECTIONS = {
    'osm-node-244081152': {
        'original': {'text': '永州市', 'lang': 'zh-Hans'},
        'expected_zh': ['永州之市'],
        'literal_meanings': [{'translations': {
            'zh': '永山与永水之州',
            'en': 'Prefecture of Mount Yong and the Yong River',
            'ja': '永山と永水にちなむ州',
            'fr': 'Préfecture du mont Yong et de la rivière Yong',
            'es': 'Prefectura del monte Yong y el río Yong',
        }}],
        'reason': 'The original Chinese draft repeated the place name. The municipal historical review favors the earlier mountain-and-river naming chain and rejects an unsupported two-waters gloss.',
        'sources': ['https://yzcity.gov.cn/cnyz/yxxx/202604/ec8c2b5d0db94e05a7eb818d9783154c.shtml'],
    },
    'osm-node-244081239': {
        'original': {'text': '六安市', 'lang': 'zh-Hans'},
        'expected_zh': ['滨水高地安宁之城'],
        'literal_meanings': [{'translations': {
            'zh': '六地平安',
            'en': 'Peace in the land of Lu',
            'ja': '六（ルー）の地の平安',
            'fr': 'Paix sur la terre de Lu',
            'es': 'Paz en la tierra de Lu',
        }}],
        'reason': 'The original draft promoted a disputed deeper root of 六 as settled. The city government gives 六地平安, retaining 六 as the older proper place name pronounced Lu.',
        'sources': ['https://www.luan.gov.cn/zjla/lasq/lsp/2638691.html'],
    },
    'osm-node-244082431': {
        'original': {'text': '新乡市', 'lang': 'zh-Hans'},
        'expected_zh': ['新乡之城'],
        'literal_meanings': [{'translations': {
            'zh': '新的乡里',
            'en': 'New Township',
            'ja': '新しい郷',
            'fr': 'Nouveau canton',
            'es': 'Nuevo poblado',
        }}],
        'reason': 'The original Chinese draft merely restated the place name. 新乡 uses the first and last characters of older 新中乡; the clean lexical reading is new township, without claiming why the older settlement was called new.',
        'sources': ['https://hnxx.wenming.cn/wmsd/202601/t20260107_9127475.html'],
    },
    'osm-node-3006138874': {
        'original': {'text': '毕节市', 'lang': 'zh-Hans'},
        'expected_zh': ['比跻部族之城', '除夕竣工之城'],
        'literal_meanings': [{'translations': {
            'zh': '比跻部族之地',
            'en': 'Place of the Biji clan',
            'ja': '比跻氏族の地',
            'fr': 'Terre du clan Biji',
            'es': 'Tierra del clan Biji',
        }}],
        'reason': 'The local publicity department traces 毕节 to a phonetic rendering of the Yi clan Biji. The New Year construction story conflicts with the attested earlier Yuan-era name and is not a second lexical meaning.',
        'sources': ['https://m.thepaper.cn/newsDetail_forward_10345042'],
    },
    'osm-node-469624375': {
        'original': {'text': '曲靖市', 'lang': 'zh-Hans'},
        'expected_zh': ['白彝之首的城市'],
        'literal_meanings': [{'translations': {
            'zh': '曲州与靖州合成之名',
            'en': 'Name combining Qu Prefecture and Jing Prefecture',
            'ja': '曲州と靖州を合わせた地名',
            'fr': 'Nom formé de Quzhou et Jingzhou',
            'es': 'Nombre formado por Quzhou y Jingzhou',
        }}],
        'reason': 'Historical gazetteers explicitly explain 曲靖 as the combination of 曲州 and 靖州. A proposed Yi-language decomposition is not established and should not be published as a definite meaning.',
        'sources': ['https://www.shidianguji.com/book/NA02477/chapter/1l3wqu6c50etl'],
    },
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Back up and write the reviewed corrections')
    args = parser.parse_args()
    settings = Settings.from_env()
    changes = []
    already = []
    with connect(settings) as client:
        for feature_id, correction in CORRECTIONS.items():
            hit = client.get(index=settings.index, id=feature_id)
            doc = hit['_source']
            if doc['feature_id'] != feature_id or doc['kind'] != 'city' or doc.get('literal_name') != correction['original']:
                raise ValueError(f'Unexpected identity or original name: {feature_id}')
            existing = doc.get('literal_meanings', [])
            if existing == correction['literal_meanings']:
                already.append(feature_id)
                continue
            if [m['translations'].get('zh') for m in existing] != correction['expected_zh']:
                raise ValueError(f'Existing meaning changed; review manually: {feature_id}')
            patch = {'literal_meanings': correction['literal_meanings'], 'meaning_id': None}
            Feature.model_validate({**doc, **patch})
            changes.append((hit, patch))
        report = {'index': settings.index, 'changes': len(changes),
                  'already_corrected': already, 'apply': args.apply,
                  'corrections': [{
                      'feature_id': feature_id,
                      'reason': correction['reason'],
                      'sources': correction['sources'],
                  } for feature_id, correction in CORRECTIONS.items()]}
        if args.apply and changes:
            run_dir = OUTPUT_ROOT / 'editorial-review' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            run_dir.mkdir(parents=True, exist_ok=False)
            (run_dir / 'before.json').write_text(json.dumps(
                [{'hit': dict(hit), 'patch': patch} for hit, patch in changes],
                ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            for hit, patch in changes:
                client.update(index=settings.index, id=hit['_id'], doc=patch,
                              if_seq_no=hit['_seq_no'], if_primary_term=hit['_primary_term'],
                              refresh='wait_for')
            report['backup_dir'] = str(run_dir.resolve())
            (run_dir / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            (OUTPUT_ROOT / 'editorial-corrections.json').write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
