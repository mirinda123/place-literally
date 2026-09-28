"""Pin the selected Chinese OSM city spellings before translation."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from .config import ROOT, Settings, connect
from .indexing import Feature


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path,
                        default=ROOT / 'work/osm-china-cities/additional-30/plan-30.json')
    parser.add_argument('--output-dir', type=Path,
                        default=ROOT / 'work/osm-china-cities/additional-30/name-preparation')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    targets = json.loads(args.plan.read_text(encoding='utf-8'))['selected']
    if not targets or len({item['feature_id'] for item in targets}) != len(targets):
        raise ValueError('Expected distinct Chinese city targets')
    settings = Settings.from_env()
    changes = []
    with connect(settings) as client:
        for target in targets:
            hit = client.get(index=settings.index, id=target['feature_id'])
            doc = hit['_source']
            if doc['kind'] != 'city' or target['osm'] not in doc.get('external_ids', {}).get('osm', []):
                raise ValueError(f'Identity mismatch: {target["feature_id"]}')
            name = target['local_name']
            if doc['names'].get(name['lang']) != name['text']:
                raise ValueError(f'Chinese name mismatch: {target["feature_id"]}')
            original = doc.get('literal_name')
            if original and original != name:
                raise ValueError(f'Existing original differs from selected OSM label: {target["feature_id"]}')
            if doc.get('literal_meanings') and not original:
                raise ValueError(f'Refusing to change a translated city: {target["feature_id"]}')
            if not original:
                patch = {'literal_name': name}
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
