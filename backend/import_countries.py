"""Merge collected OSM country names into the existing features index."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from elasticsearch import helpers

from .config import ROOT, Settings, connect
from .indexing import SCHEMA, documents, ensure_name_search


def mapping_field_count(properties):
    return sum(1 + mapping_field_count(value.get("properties", {}))
               + mapping_field_count(value.get("fields", {})) for value in properties.values())


def required_mapping_fields(mapping, actions):
    existing = set(mapping["properties"]["names"].get("properties", {}))
    incoming = {lang for action in actions for lang in action["_source"]["names"]}
    # Each new name language adds text plus its .raw keyword subfield.
    return mapping_field_count(mapping["properties"]) + 2 * len(incoming - existing) + (0 if "search_names" in mapping["properties"] else 2)


def plan_import(countries, hits, index, settlements=False, regions=False):
    if settlements and regions:
        raise ValueError("Choose settlements or regions, not both")
    by_osm = {}
    by_id = {hit["_id"]: hit for hit in hits}
    for hit in hits:
        for osm in hit["_source"].get("external_ids", {}).get("osm", []):
            by_osm.setdefault(osm, []).append(hit)
    actions, seen = [], set()
    stats = {"created": 0, "updated": 0, "unchanged": 0}
    for country in countries:
        osm = country["osm"]
        if osm in seen:
            raise ValueError(f"Duplicate input identity: {osm}")
        seen.add(osm)
        matches = by_osm.get(osm, [])
        if len(matches) > 1:
            raise ValueError(f"Ambiguous existing OSM identity: {osm}")
        names = dict(country["names"])
        if country.get("local_name"):
            # 'und' preserves the original label without guessing its language.
            names["und"] = country["local_name"]
        if matches:
            hit = matches[0]
            previous = hit["_source"]
            allowed = ({"state", "province"} if regions else
                       {"city", "town", "metropolis", "village", "hamlet", "suburb", "municipality", "atoll", "island", "locality"}
                       if settlements else {"country"})
            if previous["kind"] not in allowed and not (settlements and previous["kind"] == country["kind"]):
                raise ValueError(f"OSM identity belongs to another feature kind: {osm}")
            # Keep curated names, coordinates, meanings and the existing feature ID.
            doc = {**previous, "names": {**names, **previous["names"]}}
            doc = documents([doc])[0]
            if doc == previous:
                stats["unchanged"] += 1
                continue
            action = {"_op_type": "index", "_id": hit["_id"], "_source": doc,
                      "if_seq_no": hit["_seq_no"], "if_primary_term": hit["_primary_term"]}
            stats["updated"] += 1
        else:
            feature_id = "osm-" + osm.replace("/", "-")
            if feature_id in by_id:
                raise ValueError(f"Generated feature ID already belongs to another record: {feature_id}")
            doc = documents([{
                "feature_id": feature_id, "kind": country["kind"] if settlements or regions else "country", "names": names,
                "location": country["location"], "external_ids": {"osm": [osm]},
            }])[0]
            action = {"_op_type": "create", "_id": feature_id, "_source": doc}
            stats["created"] += 1
        actions.append({"_index": index, **action})
    return actions, stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--cities", action="store_true", help="Import the selected city export using the same OSM merge rules")
    mode.add_argument("--regions", action="store_true", help="Import selected province-level place nodes")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    args.input = args.input or ROOT / ("work/osm-china-regions/regions.json" if args.regions else
                                        "work/osm-cities/cities.json" if args.cities else "work/osm-countries/countries.json")
    args.output_dir = args.output_dir or ROOT / ("work/osm-region-imports" if args.regions else
                                                "work/osm-city-imports" if args.cities else "work/osm-country-imports")
    countries = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(countries, list) or not countries:
        raise ValueError("Expected a nonempty country export")
    settings = Settings.from_env()
    with connect(settings) as client:
        mapping = client.indices.get_mapping(index=settings.index)[settings.index]["mappings"]
        if mapping.get("_meta", {}).get("schema") != SCHEMA:
            raise ValueError("Expected an existing features index with the required schema")
        hits = list(helpers.scan(client, index=settings.index,
                    query={"query": {"match_all": {}}, "seq_no_primary_term": True}))
        actions, stats = plan_import(countries, hits, settings.index, settlements=args.cities, regions=args.regions)
        report = {"index": settings.index, "input": str(args.input.resolve()),
                  "before": len(hits), "source_records": len(countries), "mode": "regions" if args.regions else "cities" if args.cities else "countries", **stats,
                  "dry_run": args.dry_run}
        projected_fields = required_mapping_fields(mapping, actions)
        index_settings = client.indices.get_settings(index=settings.index, flat_settings=True, include_defaults=True)[settings.index]
        setting_key = "index.mapping.total_fields.limit"
        field_limit = int(index_settings["settings"].get(setting_key, index_settings.get("defaults", {}).get(setting_key, 1000)))
        next_limit = max(field_limit, ((projected_fields + 499) // 500) * 500)
        if next_limit > 5000:
            raise ValueError("Language fields exceed the bounded importer capacity; review the schema before importing")
        report.update(projected_mapping_fields=projected_fields, field_limit_before=field_limit, field_limit_after=next_limit)
        if not args.dry_run:
            run_dir = args.output_dir / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            run_dir.mkdir(parents=True, exist_ok=False)
            # Save a complete document backup before the first ES write.
            (run_dir / "before.json").write_text(json.dumps(
                [{"_id": h["_id"], "_source": h["_source"]} for h in hits],
                ensure_ascii=False, indent=2), encoding="utf-8")
            (run_dir / "actions.json").write_text(json.dumps(actions, ensure_ascii=False, indent=2), encoding="utf-8")
            (run_dir / "mapping-before.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
            if next_limit > field_limit:
                client.indices.put_settings(index=settings.index, settings={setting_key: next_limit})
            ensure_name_search(client, settings)
            # Migration can change sequence numbers; re-read before optimistic writes.
            fresh_hits = list(helpers.scan(client, index=settings.index,
                query={"query": {"match_all": {}}, "seq_no_primary_term": True}))
            actions, stats = plan_import(countries, fresh_hits, settings.index, settlements=args.cities, regions=args.regions)
            report.update(stats)
            (run_dir / "actions.json").write_text(json.dumps(actions, ensure_ascii=False, indent=2), encoding="utf-8")
            if actions:
                count, errors = helpers.bulk(client, actions, refresh="wait_for", raise_on_error=False)
            else:
                count, errors = 0, []
            report.update(written=count, errors=errors, after=client.count(index=settings.index)["count"],
                          backup_dir=str(run_dir.resolve()))
            (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            if errors:
                print(json.dumps(report, ensure_ascii=True))
                raise SystemExit("Some writes failed; inspect report.json before retrying")
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
