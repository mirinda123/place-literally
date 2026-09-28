"""Cache major settlement nodes from Overpass; global or selected country areas."""
import argparse
from collections import Counter
import gzip
import json
import math
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from scripts.collect_osm_countries import ENDPOINT, LANGUAGE, TARGET_LANGUAGES, retry_wait, timestamp, write_json

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 128 * 1024 * 1024


def build_query(country=None, threshold=50000, count=False, layer="all"):
    if threshold < 1:
        raise ValueError("Population threshold must be positive")
    prefix, area = "", ""
    if country:
        if not re.fullmatch(r"[A-Z]{2}", country):
            raise ValueError("Expected a two-letter country code")
        prefix = f'area["ISO3166-1"="{country}"]["boundary"="administrative"]["admin_level"="2"]->.country;\n'
        area = "(area.country)"
    # Simple indexed selectors; population parsing/filtering happens locally.
    min_extra_chars = max(0, len(str(threshold)) - 1)
    layers = {"cities": f'node{area}["place"="city"];',
              "towns": f'node{area}["place"="town"]["population"~"^[0-9][0-9, \\u00a0\\u202f]{{{min_extra_chars},}}$"];',
              "capitals": f'node{area}["capital"="yes"]["place"];node{area}["capital"="2"]["place"];node{area}["capital"="4"]["place"];'}
    selection = "(" + ("".join(layers.values()) if layer == "all" else layers[layer]) + ");"
    # Country scopes also output their matched areas so missing/ambiguous boundaries
    # cannot be silently treated as an empty successful export.
    verification = ".country out tags;\n" if country else ""
    budget = '[out:json][timeout:300][maxsize:268435456];\n' if layer == "towns" else '[out:json][timeout:180][maxsize:134217728];\n'
    return budget + prefix + verification + selection + ("\nout count;" if count else "\nout body;")


def population(value):
    value = (value or "").strip()
    if re.fullmatch(r"[0-9]+", value):
        return int(value)
    if re.fullmatch(r"[0-9]{1,3}(?:,[0-9]{3})+", value):
        return int(value.replace(",", ""))
    if re.fullmatch(r"[0-9]{1,3}(?:[ \u00a0\u202f][0-9]{3})+", value):
        return int(re.sub(r"\s", "", value))
    return None


def select_reason(tags, threshold=50000):
    if tags.get("capital") in ("yes", "2"):
        return "national_capital"
    if tags.get("capital") == "4":
        return "admin_level_4_capital"
    if tags.get("place") not in ("city", "town"):
        return None
    size = population(tags.get("population"))
    if size is not None:
        return "population_threshold" if size >= threshold else None
    return "city_unknown_population" if tags.get("place") == "city" else None


def validate(payload, country=None):
    if not isinstance(payload, dict) or payload.get("remark") or not isinstance(payload.get("elements"), list):
        raise ValueError("Overpass returned an error or incomplete response: " + str(payload.get("remark", "invalid JSON structure") if isinstance(payload, dict) else "invalid structure"))
    areas = [e for e in payload["elements"] if e.get("type") == "area"]
    if country and (len(areas) != 1 or areas[0].get("tags", {}).get("ISO3166-1") != country):
        raise ValueError(f"Missing or ambiguous country boundary: {country}")
    seen = set()
    for item in payload["elements"]:
        if item.get("type") in ("area", "count"):
            continue
        if item.get("type") != "node" or type(item.get("id")) is not int or item["id"] <= 0:
            raise ValueError("Expected a valid OSM node")
        if item["id"] in seen:
            raise ValueError("Duplicate node in response")
        seen.add(item["id"])
        tags = item.get("tags", {})
        if not isinstance(tags, dict) or not tags.get("place"):
            raise ValueError("Expected settlement tags")
        if any(not isinstance(k, str) or not isinstance(v, str) for k, v in tags.items()):
            raise ValueError("Invalid tags")
        for key, bound in (("lat", 90), ("lon", 180)):
            value = item.get(key)
            if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > bound:
                raise ValueError("Invalid node coordinates")
    return payload


class Overpass:
    def __init__(self, endpoint=ENDPOINT, interval=10, attempts=3, opener=urllib.request.urlopen, sleep=time.sleep):
        if urllib.parse.urlsplit(endpoint).scheme != "https":
            raise ValueError("Use HTTPS")
        self.endpoint, self.interval, self.attempts = endpoint, interval, attempts
        self.opener, self.sleep, self.last = opener, sleep, None

    def fetch(self, query, country=None):
        for attempt in range(self.attempts):
            if self.last is not None:
                self.sleep(max(0, self.interval - (time.monotonic() - self.last)))
            request = urllib.request.Request(self.endpoint,
                data=urllib.parse.urlencode({"data": query}).encode(), headers={
                    "User-Agent": "LiteralNameMap-CityCollector/1.0 (cached settlement export)",
                    "Content-Type": "application/x-www-form-urlencoded", "Accept-Encoding": "gzip"})
            headers = None
            try:
                with self.opener(request, timeout=330) as response:
                    if response.headers.get("Content-Encoding") == "gzip":
                        with gzip.GzipFile(fileobj=response) as compressed:
                            body = compressed.read(MAX_BYTES + 1)
                    else:
                        body = response.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES:
                    raise ValueError("Export too large; use selected country scopes")
                return validate(json.loads(body), country)
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 502, 503, 504) or attempt + 1 >= self.attempts:
                    raise
                headers = exc.headers
            except (urllib.error.URLError, TimeoutError):
                if attempt + 1 >= self.attempts:
                    raise
            finally:
                self.last = time.monotonic()
            delay = retry_wait(headers, attempt, 30)
            print(f"Overpass busy; waiting {delay:g}s, retry {attempt + 2}/{self.attempts}", flush=True)
            self.sleep(delay)
        raise RuntimeError("No attempts configured")


def transform(payloads, threshold):
    nodes, origins = {}, {}
    for scope, payload in payloads.items():
        for item in payload["elements"]:
            if item["type"] != "node":
                continue
            osm = f'node/{item["id"]}'
            if osm in nodes and nodes[osm] != item:
                raise ValueError(f"Conflicting snapshots for {osm}; refresh the involved caches")
            nodes[osm] = item
            origins.setdefault(osm, []).append(scope)
    selected, rejected, reasons, languages = [], Counter(), Counter(), Counter()
    for osm, item in sorted(nodes.items()):
        tags = item["tags"]
        if tags.get("place") == "country":
            rejected["country_node"] += 1
            continue
        reason = select_reason(tags, threshold)
        if not reason:
            rejected["below_threshold_or_unknown_town"] += 1
            continue
        names = {key[5:]: value for key, value in tags.items()
                 if key.startswith("name:") and LANGUAGE.fullmatch(key[5:]) and value.strip()}
        if not names and not tags.get("name", "").strip():
            rejected["no_name"] += 1
            continue
        reasons[reason] += 1
        languages.update(names.keys())
        selected.append({"osm": osm, "kind": tags["place"], "local_name": tags.get("name"), "names": names,
            "location": {"lon": item["lon"], "lat": item["lat"]}, "population": population(tags.get("population")),
            "population_raw": tags.get("population"), "population_date": tags.get("population:date"),
            "population_source": tags.get("source:population"), "capital": tags.get("capital"),
            "selection_reason": reason, "query_scopes": origins[osm]})
    return selected, {"candidate_nodes": len(nodes), "selected": len(selected), "rejected": dict(rejected),
        "selection_reasons": dict(reasons), "language_tags": len(languages),
        "target_language_coverage": {lang: languages[lang] for lang in TARGET_LANGUAGES}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--countries", nargs="+", help="Optional ISO alpha-2 country scopes, e.g. CN JP FR; default global")
    parser.add_argument("--min-population", type=int, default=50000)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "work/osm-cities")
    parser.add_argument("--endpoint", default=ENDPOINT)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--count", action="store_true", help="Count candidates without downloading names")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    client, payloads, failures = Overpass(args.endpoint), {}, {}
    scopes = list(dict.fromkeys(args.countries or ["global-cities", "global-towns", "global-capitals"]))
    for scope in scopes:
        country = None if scope.startswith("global-") else scope.upper()
        layer = scope.removeprefix("global-") if country is None else "all"
        query = build_query(country, args.min_population, args.count, layer)
        cache = args.output_dir / f'{scope}-{args.min_population}{"-count" if args.count else ""}.raw.json'
        try:
            if cache.exists() and not args.refresh:
                bundle = json.loads(cache.read_text(encoding="utf-8"))
                if bundle["query"] != query or bundle["endpoint"] != args.endpoint:
                    raise ValueError("Cache configuration differs; use --refresh")
                validate(bundle["response"], country)
                print(f"{scope}: using cache", flush=True)
            else:
                print(f"{scope}: requesting Overpass", flush=True)
                response = client.fetch(query, country)
                bundle = {"query": query, "endpoint": args.endpoint, "retrieved_at": timestamp(), "response": response}
                write_json(cache, bundle)
            payloads[scope] = bundle["response"]
            if args.count:
                print(json.dumps({"scope": scope, "counts": [e["tags"] for e in payloads[scope]["elements"] if e["type"] == "count"]}))
        except (OSError, ValueError, RuntimeError) as exc:
            failures[scope] = str(exc)
            print(f"{scope}: {exc}", file=sys.stderr, flush=True)
            # Stop the run after exhausted retries; don't hammer other scopes.
            break
    if args.count:
        return 1 if failures else 0
    report = {"scopes": scopes, "completed_scopes": list(payloads), "failures": failures,
        "threshold": args.min_population, "generated_at": timestamp(),
        "attribution": "© OpenStreetMap contributors", "license": "ODbL-1.0",
        "license_url": "https://www.openstreetmap.org/copyright",
        "notes": ["Administrative-level 4 capitals are included; this is not every country's first subdivision level.",
                  "Global scope does not infer country membership; original node tags remain in the raw cache."]}
    if failures:
        write_json(args.output_dir / "failed-run.json", report)
        return 1
    cities, stats = transform(payloads, args.min_population)
    if not cities:
        raise ValueError("No cities selected; no import file published")
    report.update(stats)
    write_json(args.output_dir / "cities.json", cities)
    write_json(args.output_dir / "report.json", report)
    print(json.dumps(report, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
