"""Pin locally attested OSM city names before translating European cities."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from .config import ROOT, Settings, connect
from .indexing import Feature


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=ROOT / 'work/osm-europe-cities/plan-45.json')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'work/osm-europe-cities/name-preparation')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding='utf-8'))
    targets = plan['selected']
    if not targets or len({t['feature_id'] for t in targets}) != len(targets):
        raise ValueError('Expected distinct planned cities')
    settings = Settings.from_env()
    changes = []
    with connect(settings) as client:
        for target in targets:
            hit = client.get(index=settings.index, id=target['feature_id'])
            doc = hit['_source']
            if doc['kind'] != 'city' or target['osm'] not in doc.get('external_ids', {}).get('osm', []):
                raise ValueError(f'Identity mismatch: {target["feature_id"]}')
            name = target['local_name']
            if name['text'] not in doc['names'].values():
                raise ValueError(f'Stale local name: {target["feature_id"]}')
            existing = doc.get('literal_name')
            if existing:
                if existing != name:
                    raise ValueError(f'Existing original differs from planned local name: {target["feature_id"]}')
            if doc.get('literal_meanings'):
                raise ValueError(f'Refusing to replace existing meanings: {target["feature_id"]}')
            patch = {}
            if doc['names'].get(name['lang']) != name['text']:
                patch['names'] = {**doc['names'], name['lang']: name['text']}
            if not existing:
                patch['literal_name'] = name
            if patch:
                Feature.model_validate({**doc, **patch})
                changes.append((hit, patch))
        report = {'index': settings.index, 'targets': len(targets), 'already_pinned': len(targets) - len(changes),
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
