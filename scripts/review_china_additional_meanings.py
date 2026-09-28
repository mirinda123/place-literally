"""Correct two misleading interpretations in the additional China city batch."""

import json
from datetime import datetime, timezone

from backend.config import ROOT, Settings, connect
from backend.indexing import Feature


OUTPUT_ROOT = ROOT / 'work/literal-translations/china-additional-cities-20260925'
CORRECTIONS = {
    'osm-node-244083205': {
        'original': {'text': '中山市', 'lang': 'zh-Hans'},
        'expected_zh': ['中间的山之城'],
        'literal_meanings': [{'translations': {
            'zh': '孙中山的别号“中山”（中间的山）',
            'en': 'Sun Yat-sen’s alias Zhongshan (“middle mountain”)',
            'ja': '孫文の別号「中山」（中央の山）',
            'fr': 'Le surnom Zhongshan de Sun Yat-sen (« montagne du milieu »)',
            'es': 'El seudónimo Zhongshan de Sun Yat-sen (« montaña del medio »)',
        }}],
        'reason': 'The city was named in memory of Sun Yat-sen. The earlier gloss read as though a middle mountain at the city were the namesake; retain the alias context alongside the literal words.',
        'sources': [
            'https://www.zs.gov.cn/zjzs/zsgk/content/mpost_216040.html',
            'https://www.zs.gov.cn/nlz/zjnl/nlgk/lsmr/content/post_1308324.html',
        ],
    },
    'osm-node-3009802821': {
        'original': {'text': '昆明市', 'lang': 'zh-Hans'},
        'expected_zh': ['湖畔之城'],
        'literal_meanings': [],
        'reason': 'Kunming is an older ethnic name. The Yi-language water-side reading is one of several unproven proposals and does not securely refer to the present city’s lakeside site; presenting it as the sole literal meaning overstates the evidence.',
        'sources': ['https://ynmz.yn.gov.cn/cms/dimingfengcai/11216.html'],
        'status': 'uncertain',
    },
}


def main():
    settings = Settings.from_env()
    changes = []
    with connect(settings) as client:
        for feature_id, correction in CORRECTIONS.items():
            hit = client.get(index=settings.index, id=feature_id)
            doc = hit['_source']
            if doc['feature_id'] != feature_id or doc['kind'] != 'city' or doc.get('literal_name') != correction['original']:
                raise ValueError(f'Unexpected identity or original name: {feature_id}')
            existing = doc.get('literal_meanings', [])
            if [m['translations'].get('zh') for m in existing] != correction['expected_zh']:
                raise ValueError(f'Existing meaning changed; review manually: {feature_id}')
            patch = {'literal_meanings': correction['literal_meanings'], 'meaning_id': None}
            Feature.model_validate({**doc, **patch})
            changes.append((hit, patch))
        run_dir = OUTPUT_ROOT / 'editorial-review' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / 'before.json').write_text(json.dumps(
            [{'hit': dict(hit), 'patch': patch} for hit, patch in changes],
            ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        for hit, patch in changes:
            client.update(index=settings.index, id=hit['_id'], doc=patch,
                          if_seq_no=hit['_seq_no'], if_primary_term=hit['_primary_term'],
                          refresh='wait_for')
    report = {'index': settings.index, 'backup_dir': str(run_dir.resolve()),
              'corrections': [{
                  'feature_id': feature_id,
                  'reason': correction['reason'],
                  'sources': correction['sources'],
                  'status': correction.get('status', 'corrected'),
              } for feature_id, correction in CORRECTIONS.items()]}
    (run_dir / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (OUTPUT_ROOT / 'editorial-corrections.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
