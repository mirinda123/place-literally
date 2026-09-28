"""Preserve the Japanese proper name in Shizuoka's Chinese gloss."""

import json
from datetime import datetime, timezone

from backend.config import ROOT, Settings, connect
from backend.indexing import Feature

FEATURE_ID = 'osm-node-763118317'
OUTPUT_ROOT = ROOT / 'work/literal-translations/japan-cities-20260925/editorial-review'


def main():
    settings = Settings.from_env()
    with connect(settings) as client:
        hit = client.get(index=settings.index, id=FEATURE_ID)
        doc = hit['_source']
        if doc['feature_id'] != FEATURE_ID or doc.get('literal_name') != {'text': '静岡市', 'lang': 'ja'}:
            raise ValueError('Unexpected Shizuoka identity or original name')
        meanings = doc['literal_meanings']
        if len(meanings) != 1 or meanings[0]['translations'].get('zh') != '贱机之丘':
            raise ValueError('Shizuoka Chinese gloss changed; review before editing')
        corrected = json.loads(json.dumps(meanings, ensure_ascii=False))
        corrected[0]['translations']['zh'] = '賤機之丘'
        Feature.model_validate({**doc, 'literal_meanings': corrected, 'meaning_id': None})
        run_dir = OUTPUT_ROOT / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / 'before.json').write_text(
            json.dumps({'index': settings.index, 'hit': dict(hit)}, ensure_ascii=False, indent=2) + '\n',
            encoding='utf-8')
        client.update(index=settings.index, id=hit['_id'],
            doc={'literal_meanings': corrected, 'meaning_id': None},
            if_seq_no=hit['_seq_no'], if_primary_term=hit['_primary_term'], refresh='wait_for')
    report = {
        'feature_id': FEATURE_ID, 'before_zh': '贱机之丘', 'after_zh': '賤機之丘',
        'reason': '賤機 is a Japanese proper mountain name with no secure deeper lexical meaning; preserve its spelling rather than rendering its characters as ordinary Chinese words.',
        'source': 'https://www.pref.shizuoka.jp/kensei/information/kengaiyo/1007355.html',
    }
    (run_dir / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'backup_dir': str(run_dir.resolve()), **report}, ensure_ascii=True))


if __name__ == '__main__':
    main()
