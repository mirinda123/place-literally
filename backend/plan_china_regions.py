"""Resolve 34 China region labels to unique ES feature IDs for translation."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from .config import ROOT, Settings, connect

EXISTING = (("北京", "municipality", "node/25248662", "city"),
            ("香港", "special_administrative_region", "node/24330691", "city"),
            ("臺灣", "province", "node/432425099", "country"))


def resolve_targets(regions, hits):
    if len(regions) != 31:
        raise ValueError("Expected 31 collected state nodes")
    by_osm = defaultdict(list)
    for hit in hits:
        for osm in hit["_source"].get("external_ids", {}).get("osm", []):
            by_osm[osm].append(hit["_source"])
    requested = [(item["short_label"], item["category"], item["osm"], "state") for item in regions]
    requested.extend(EXISTING)
    if len({osm for _, _, osm, _ in requested}) != 34:
        raise ValueError("Repeated OSM identity in the target set")
    targets = []
    for label, category, osm, kind in requested:
        matches = by_osm.get(osm, [])
        if len(matches) != 1 or matches[0]["kind"] != kind:
            raise ValueError(f"Missing, ambiguous, or wrong-kind target: {label} ({osm})")
        targets.append({"label": label, "category": category, "osm": osm,
                        "feature_id": matches[0]["feature_id"], "kind": kind})
    if len({item["feature_id"] for item in targets}) != 34:
        raise ValueError("Multiple region labels resolve to one feature")
    return sorted(targets, key=lambda item: item["feature_id"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "work/osm-china-regions/regions.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "work/osm-china-regions")
    args = parser.parse_args()
    regions = json.loads(args.input.read_text(encoding="utf-8"))
    osms = [item["osm"] for item in regions] + [osm for _, _, osm, _ in EXISTING]
    settings = Settings.from_env()
    with connect(settings) as client:
        hits = client.search(index=settings.index, size=100,
            query={"terms": {"external_ids.osm": osms}})["hits"]["hits"]
    targets = resolve_targets(regions, hits)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "translation-targets.json").write_text(
        json.dumps(targets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "feature-ids.json").write_text(
        json.dumps([item["feature_id"] for item in targets], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"index": settings.index, "targets": len(targets),
                      "categories": dict(Counter(item["category"] for item in targets)),
                      "kinds": dict(Counter(item["kind"] for item in targets))}, ensure_ascii=True))


if __name__ == "__main__":
    main()
