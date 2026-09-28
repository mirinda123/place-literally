"""Pin locally attested originals for the selected 80 Indian places."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

from .config import ROOT, Settings, connect
from .indexing import Feature


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=ROOT / 'work/osm-india-places/plan-80.json')
    parser.add_argument('--output-dir', type=Path,
                        default=ROOT / 'work/osm-india-places/name-preparation')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    targets = json.loads(args.plan.read_text(encoding='utf-8'))['selected']
    if len(targets) != 80 or len({target['feature_id'] for target in targets}) != 80:
        raise ValueError('Expected 80 distinct Indian places')
    settings = Settings.from_env()
    changes = []
    with connect(settings) as client:
        for target in targets:
            hit = client.get(index=settings.index, id=target['feature_id'])
            doc = hit['_source']
            if (doc['feature_id'] != target['feature_id'] or doc['kind'] != target['kind']
                    or target['osm'] not in doc.get('external_ids', {}).get('osm', [])):
                raise ValueError(f'Identity mismatch: {target["label"]}')
            if doc.get('literal_meanings'):
                raise ValueError(f'Refusing to alter translated place: {target["label"]}')
            name = target['local_name']
            existing = doc.get('literal_name')
            if existing and existing != name:
                raise ValueError(f'Existing original differs: {target["label"]}')
            prior_spelling = doc['names'].get(name['lang'])
            if prior_spelling and prior_spelling != name['text']:
                raise ValueError(f'Existing {name["lang"]} name differs: {target["label"]}')
            patch = {}
            if not prior_spelling:
                patch['names'] = {**doc['names'], name['lang']: name['text']}
            if not existing:
                patch['literal_name'] = name
            if patch:
                Feature.model_validate({**doc, **patch})
                changes.append((hit, patch))
        report = {'index': settings.index, 'targets': len(targets),
                  'original_languages': dict(Counter(item['local_name']['lang'] for item in targets)),
                  'already_pinned': len(targets) - len(changes),
                  'changes': len(changes), 'dry_run': args.dry_run}
        if changes and not args.dry_run:
            run_dir = args.output_dir / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            run_dir.mkdir(parents=True, exist_ok=False)
            (run_dir / 'before.json').write_text(json.dumps(
                [{'before': dict(hit), 'patch': patch} for hit, patch in changes],
                ensure_ascii=False, indent=2), encoding='utf-8')
            for hit, patch in changes:
                client.update(index=settings.index, id=hit['_id'], doc=patch,
                              if_seq_no=hit['_seq_no'], if_primary_term=hit['_primary_term'])
            client.indices.refresh(index=settings.index)
            report['backup_dir'] = str(run_dir.resolve())
    print(json.dumps(report, ensure_ascii=True))


if __name__ == '__main__':
    main()
