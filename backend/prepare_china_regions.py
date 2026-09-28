"""Pin the attested Chinese label before translating province-level names."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from .config import ROOT, Settings, connect
from .indexing import Feature


def patch_for(doc, reset=False):
    if doc["kind"] != "state":
        raise ValueError("Only newly imported state labels may be prepared")
    name = next(({"text": doc["names"][lang], "lang": lang} for lang in ("zh-Hans", "zh")
                 if doc["names"].get(lang)), None)
    if name is None:
        raise ValueError(f"No tagged Chinese name for {doc['feature_id']}")
    if doc.get("literal_meanings") and doc.get("literal_name") != name and not reset:
        raise ValueError(f"Existing meaning has a different original name: {doc['feature_id']}")
    patch = {"literal_name": name}
    if reset:
        patch.update(literal_meanings=[], meaning_id=None)
    Feature.model_validate({**doc, **patch})
    return {key: value for key, value in patch.items() if doc.get(key) != value}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", type=Path, default=ROOT / "work/osm-china-regions/translation-targets.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "work/osm-china-regions/name-preparation")
    parser.add_argument("--reset-feature-id", action="append", default=[],
                        help="Clear a known incorrect draft when changing its original-name choice")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    targets = json.loads(args.targets.read_text(encoding="utf-8"))
    state_ids = [item["feature_id"] for item in targets if item["kind"] == "state"]
    if len(state_ids) != 31 or len(set(state_ids)) != 31:
        raise ValueError("Expected 31 distinct state labels")
    resets = set(args.reset_feature_id)
    if not resets <= set(state_ids):
        raise ValueError("Reset IDs must belong to this state-label batch")
    settings = Settings.from_env()
    with connect(settings) as client:
        hits = [client.get(index=settings.index, id=feature_id) for feature_id in state_ids]
        changes = [(hit, patch_for(hit["_source"], hit["_id"] in resets)) for hit in hits]
        changes = [(hit, patch) for hit, patch in changes if patch]
        report = {"index": settings.index, "state_labels": len(state_ids),
                  "changes": len(changes), "reset_ids": sorted(resets), "dry_run": args.dry_run}
        if changes and not args.dry_run:
            run_dir = args.output_dir / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            run_dir.mkdir(parents=True, exist_ok=False)
            backup = [{"before": dict(hit), "patch": patch} for hit, patch in changes]
            (run_dir / "before.json").write_text(json.dumps(backup, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            for hit, patch in changes:
                client.update(index=settings.index, id=hit["_id"], doc=patch,
                    if_seq_no=hit["_seq_no"], if_primary_term=hit["_primary_term"])
            client.indices.refresh(index=settings.index)
            report["backup_dir"] = str(run_dir.resolve())
        print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
