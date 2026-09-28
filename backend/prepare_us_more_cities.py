"""Pin 50 selected US city labels as English originals before translation."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from .config import ROOT, Settings, connect
from .indexing import Feature


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path,
                        default=ROOT / 'work/osm-us-cities/additional-50/plan-50.json')
    parser.add_argument('--output-dir', type=Path,
                        default=ROOT / 'work/osm-us-cities/additional-50/name-preparation')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    targets = json.loads(args.plan.read_text(encoding='utf-8'))['selected']
    if len(targets) != 50 or len({item['feature_id'] for item in targets}) != 50:
        raise ValueError('Expected 50 distinct US city targets')
    settings = Settings.from_env()
    changes = []
    with connect(settings) as client:
        for target in targets:
            hit = client.get(index=settings.index, id=target['feature_id'])
            doc = hit['_source']
            if doc['kind'] != 'city' or target['osm'] not in doc.get('external_ids', {}).get('osm', []):
                raise ValueError(f'Identity mismatch: {target["feature_id"]}')
            name = target['local_name']
            if name['lang'] != 'en' or name['text'] not in doc['names'].values():
                raise ValueError(f'English city name mismatch: {target["feature_id"]}')
            if doc.get('literal_meanings'):
                raise ValueError(f'Refusing to alter translated city: {target["feature_id"]}')
            if doc.get('literal_name') and doc['literal_name'] != name:
                raise ValueError(f'Existing original differs: {target["feature_id"]}')
            patch = {}
            if doc['names'].get('en') != name['text']:
                patch['names'] = {**doc['names'], 'en': name['text']}
            if not doc.get('literal_name'):
                patch['literal_name'] = name
            if patch:
                Feature.model_validate({**doc, **patch})
                changes.append((hit, patch))
        report = {'index': settings.index, 'targets': len(targets),
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
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
