"""Collect OSM country label names with one bounded Overpass query (stdlib only)."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

QUERY = '[out:json][timeout:90][maxsize:33554432];node["place"="country"];out body;'
ENDPOINT = "https://overpass-api.de/api/interpreter"
TARGET_LANGUAGES = ("en", "zh-Hans", "zh-Hant", "es", "fr", "ja", "ko")
# OSM tags also contain name:etymology, name:source, etc. Those are not languages.
# Keep all original name:* tags separately, including nonstandard language tags.
LANGUAGE = re.compile(r"[a-z]{2,3}(?:-[A-Za-z0-9]{1,8})*")
MAX_BYTES = 16 * 1024 * 1024


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def validate_response(payload):
    if not isinstance(payload, dict) or payload.get("remark"):
        raise ValueError("Overpass reported an error or partial result; nothing will be published")
    elements = payload.get("elements")
    if not isinstance(elements, list) or not elements:
        raise ValueError("Overpass returned no country nodes")
    seen = set()
    for item in elements:
        if not isinstance(item, dict) or item.get("type") != "node":
            raise ValueError("Expected country nodes only")
        osm_id = item.get("id")
        if type(osm_id) is not int or osm_id <= 0 or osm_id in seen:
            raise ValueError("Missing, invalid or duplicate OSM node ID")
        seen.add(osm_id)
        tags = item.get("tags")
        if not isinstance(tags, dict) or tags.get("place") != "country":
            raise ValueError("Unexpected non-country object")
        if any(not isinstance(k, str) or not isinstance(v, str) for k, v in tags.items()):
            raise ValueError("Invalid OSM tags")
        for key, bound in (("lat", 90), ("lon", 180)):
            value = item.get(key)
            if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > bound:
                raise ValueError("Missing or invalid country label coordinates")
    return elements


def transform(payload):
    countries = []
    codes = defaultdict(list)
    ignored = Counter()
    coverage = Counter()
    for item in validate_response(payload):
        tags = item["tags"]
        name_tags = {k: v for k, v in sorted(tags.items()) if k.startswith("name:")}
        names = {k[5:]: v for k, v in name_tags.items() if LANGUAGE.fullmatch(k[5:]) and v.strip()}
        for key in name_tags:
            if not LANGUAGE.fullmatch(key[5:]):
                ignored[key] += 1
        osm = f'node/{item["id"]}'
        code = tags.get("ISO3166-1:alpha2") or tags.get("country_code_iso3166_1_alpha_2")
        if code:
            codes[code].append(osm)
        missing = [lang for lang in TARGET_LANGUAGES if lang not in names]
        coverage.update(names.keys())
        countries.append({
            "osm": osm,
            "local_name": tags.get("name"),
            "names": names,
            "location": {"lon": item["lon"], "lat": item["lat"]},
            "country_code": code,
            "wikidata": tags.get("wikidata"),
            "name_tags": name_tags,
            "missing_languages": missing,
        })
    countries.sort(key=lambda c: (c["country_code"] or "~", c["osm"]))
    report = {
        "scope": 'All nodes tagged place=country in this Overpass snapshot; not an authoritative sovereign-state list.',
        "country_node_count": len(countries),
        "language_tag_count": len(coverage),
        "name_count": sum(coverage.values()),
        "target_language_coverage": {lang: coverage[lang] for lang in TARGET_LANGUAGES},
        "language_coverage": dict(sorted(coverage.items())),
        "duplicate_country_codes": {k: v for k, v in sorted(codes.items()) if len(v) > 1},
        "missing_country_code": [c["osm"] for c in countries if not c["country_code"]],
        "missing_local_name": [c["osm"] for c in countries if not c["local_name"]],
        "unclassified_name_tags": dict(sorted(ignored.items())),
        "notes": [
            "Names are existing OSM labels, not literal meanings or machine translations.",
            "Missing languages remain missing; name:zh is not silently assigned to zh-Hans or zh-Hant.",
            "Objects are kept separately by OSM identity; duplicate ISO codes are reported, not merged.",
            "Language keys are syntactically filtered, not validated against a language registry; raw tags are retained.",
        ],
    }
    return countries, report


def retry_wait(headers, attempt, base_delay):
    delay = base_delay * (2 ** attempt)
    value = headers.get("Retry-After") if headers else None
    if value:
        try:
            server_delay = float(value)
        except ValueError:
            try:
                server_delay = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError):
                server_delay = 0
        delay = max(delay, server_delay)
    if not math.isfinite(delay) or delay > 300:
        raise RuntimeError("Server requests a long cooldown; retry manually later")
    return delay


def fetch_countries(endpoint, attempts=3, retry_delay=30, opener=urllib.request.urlopen, sleep=time.sleep):
    if urllib.parse.urlsplit(endpoint).scheme != "https":
        raise ValueError("Use an HTTPS Overpass endpoint")
    for attempt in range(attempts):
        request = urllib.request.Request(endpoint,
            data=urllib.parse.urlencode({"data": QUERY}).encode("utf-8"),
            headers={"User-Agent": "LiteralNameMap-CountryCollector/1.0 (bounded country-label export)",
                     "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        headers = None
        try:
            with opener(request, timeout=120) as response:
                body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise ValueError("Response exceeded the country export size limit")
            payload = json.loads(body)
            validate_response(payload)
            return payload
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 502, 503, 504) or attempt + 1 >= attempts:
                raise
            headers = exc.headers
        except (urllib.error.URLError, TimeoutError):
            if attempt + 1 >= attempts:
                raise
        delay = retry_wait(headers, attempt, retry_delay)
        print(f"Request unavailable; waiting {delay:g}s before retry {attempt + 2}/{attempts}", file=sys.stderr, flush=True)
        sleep(delay)
    raise RuntimeError("No request attempts configured")


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def collect(output_dir, endpoint=ENDPOINT, refresh=False, attempts=3, retry_delay=30):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "overpass-countries.raw.json"
    cached = raw_path.exists() and not refresh
    if cached:
        bundle = json.loads(raw_path.read_text(encoding="utf-8"))
        if bundle.get("query") != QUERY or bundle.get("endpoint") != endpoint:
            raise ValueError("Cache belongs to a different query or endpoint; use another output directory or --refresh")
    else:
        bundle = {"query": QUERY, "endpoint": endpoint, "response": fetch_countries(endpoint, attempts, retry_delay),
                  "retrieved_at": timestamp()}
    countries, report = transform(bundle["response"])
    report.update(query=QUERY, endpoint=bundle["endpoint"], retrieved_at=bundle["retrieved_at"],
                  osm_base_timestamp=bundle["response"].get("osm3s", {}).get("timestamp_osm_base"),
                  generated_at=timestamp(), used_cache=cached,
                  attribution="© OpenStreetMap contributors", license="ODbL-1.0",
                  license_url="https://www.openstreetmap.org/copyright")
    if not cached:
        write_json(raw_path, bundle)
    write_json(output_dir / "countries.json", countries)
    write_json(output_dir / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parents[1] / "work/osm-countries")
    parser.add_argument("--endpoint", default=ENDPOINT)
    parser.add_argument("--refresh", action="store_true", help="Fetch a new snapshot instead of reusing local raw data")
    parser.add_argument("--attempts", type=int, choices=range(1, 4), default=3)
    args = parser.parse_args()
    try:
        report = collect(args.output_dir, args.endpoint, args.refresh, args.attempts)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Collection failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"output_dir": str(args.output_dir.resolve()), "cached": report["used_cache"],
                      "country_nodes": report["country_node_count"], "languages": report["language_tag_count"],
                      "coverage": report["target_language_coverage"]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
