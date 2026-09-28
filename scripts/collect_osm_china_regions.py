"""Select Chinese province-level map labels from a cached Overpass snapshot.

The 31 selected state nodes cover 22 mainland provinces, five autonomous
regions, three municipalities, and Macau. Beijing, Hong Kong, and Taiwan use
already indexed place labels; they are included in the translation batch by ID.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

from scripts.collect_osm_cities import Overpass
from scripts.collect_osm_countries import ENDPOINT, LANGUAGE, TARGET_LANGUAGES, timestamp, write_json

ROOT = Path(__file__).resolve().parents[1]
QUERY = '[out:json][timeout:120][maxsize:67108864];node["place"~"^(state|province)$"](17,73,54,135);out body;'

# Short labels are selectors, not new translations. Match them only against
# language-tagged OSM names and reject missing or ambiguous matches.
REGIONS = {
    "province": ("安徽", "福建", "甘肃", "贵州", "广东", "河北", "黑龙江", "河南", "海南",
                 "湖北", "湖南", "江苏", "江西", "吉林", "辽宁", "青海", "山西", "山东",
                 "陕西", "四川", "云南", "浙江"),
    "autonomous_region": ("广西", "宁夏", "内蒙古", "新疆", "西藏"),
    "municipality": ("天津", "上海", "重庆"),
    "special_administrative_region": ("澳门",),
}
VARIANTS = {"陕西": ("陕西", "陝西"), "澳门": ("澳门", "澳門")}


def transform(payload):
    if not isinstance(payload, dict) or payload.get("remark") or not isinstance(payload.get("elements"), list):
        raise ValueError("Overpass returned an incomplete state-label export")
    elements = payload["elements"]
    if len(elements) > 1000:
        raise ValueError("Unexpectedly broad state-label export")
    regions = []
    for category, labels in REGIONS.items():
        for label in labels:
            prefixes = VARIANTS.get(label, (label,))
            matches = []
            for item in elements:
                tags = item.get("tags", {})
                if item.get("type") != "node" or tags.get("place") != "state":
                    continue
                chinese = [tags.get(key, "") for key in ("name:zh", "name:zh-Hans", "name:zh-Hant")]
                if any(name.startswith(prefix) for name in chinese for prefix in prefixes):
                    matches.append(item)
            if len(matches) != 1:
                raise ValueError(f"Expected one OSM state node for {label}, found {len(matches)}")
            item = matches[0]
            tags = item["tags"]
            names = {key[5:]: value for key, value in tags.items()
                     if key.startswith("name:") and LANGUAGE.fullmatch(key[5:]) and value.strip()}
            if not names or not tags.get("name", "").strip():
                raise ValueError(f"Missing name for {label}")
            regions.append({"osm": f'node/{item["id"]}', "kind": "state", "category": category,
                            "short_label": label, "local_name": tags["name"], "names": names,
                            "location": {"lon": item["lon"], "lat": item["lat"]}})
    if len(regions) != 31 or len({item["osm"] for item in regions}) != 31:
        raise ValueError("Expected 31 distinct province-level state nodes")
    regions.sort(key=lambda item: item["osm"])
    return regions


def collect(output_dir, endpoint=ENDPOINT, refresh=False):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "state-candidates.raw.json"
    if raw_path.exists() and not refresh:
        bundle = json.loads(raw_path.read_text(encoding="utf-8"))
        if bundle.get("query") != QUERY or bundle.get("endpoint") != endpoint:
            raise ValueError("Cached Overpass query differs; use another directory or --refresh")
        cached = True
    else:
        bundle = {"query": QUERY, "endpoint": endpoint, "retrieved_at": timestamp(),
                  "response": Overpass(endpoint).fetch(QUERY)}
        write_json(raw_path, bundle)
        cached = False
    regions = transform(bundle["response"])
    coverage = Counter(lang for region in regions for lang in region["names"])
    report = {"selected": len(regions), "categories": dict(Counter(item["category"] for item in regions)),
              "target_language_coverage": {lang: coverage[lang] for lang in TARGET_LANGUAGES},
              "unmatched_existing_labels": ["北京", "香港", "臺灣"],
              "query": QUERY, "endpoint": endpoint, "retrieved_at": bundle["retrieved_at"],
              "generated_at": timestamp(), "used_cache": cached,
              "attribution": "© OpenStreetMap contributors", "license": "ODbL-1.0",
              "license_url": "https://www.openstreetmap.org/copyright"}
    write_json(output_dir / "regions.json", regions)
    write_json(output_dir / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "work/osm-china-regions")
    parser.add_argument("--endpoint", default=ENDPOINT)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    report = collect(args.output_dir, args.endpoint, args.refresh)
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
