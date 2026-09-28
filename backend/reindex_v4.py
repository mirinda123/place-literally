"""Copy v3 features into a new v4 index with English and Japanese meaning analyzers."""
import argparse
import json
from dataclasses import replace

from .config import Settings, connect
from .indexing import SCHEMA, import_seed


def reindex_v4(client, settings, source, target):
    if source == target or client.indices.exists(index=target):
        raise ValueError("The target must be a new index; existing data is never overwritten")
    source_mapping = client.indices.get_mapping(index=source)[source]["mappings"]
    source_meta = source_mapping.get("_meta", {})
    if source_meta.get("schema") != "literal-name-map-features-v3":
        raise ValueError("The source must use the v3 features schema")

    target_settings = replace(settings, index=target, analyzer=source_meta["analyzer"])
    import_seed(client, target_settings, [])
    source_settings = client.indices.get_settings(index=source, flat_settings=True, include_defaults=True)[source]
    field_key = "index.mapping.total_fields.limit"
    source_limit = int(source_settings["settings"].get(field_key,
                       source_settings.get("defaults", {}).get(field_key, 1000)))
    client.indices.put_settings(index=target, settings={field_key: max(2000, source_limit + 200)})

    expected = client.count(index=source)["count"]
    result = client.options(request_timeout=900).reindex(
        source={"index": source}, dest={"index": target}, refresh=True)
    source_count = client.count(index=source)["count"]
    target_count = client.count(index=target)["count"]
    if (result.get("failures") or result.get("version_conflicts")
            or result["created"] != expected or source_count != expected or target_count != expected):
        raise ValueError(f"Reindex incomplete: before={expected}, source={source_count}, "
                         f"target={target_count}, created={result.get('created')}, "
                         f"failures={result.get('failures')}")

    mapping = client.indices.get_mapping(index=target)[target]["mappings"]
    translations = mapping["properties"]["literal_meanings"]["properties"]["translations"]["properties"]
    if (mapping.get("_meta", {}).get("schema") != SCHEMA
            or translations["zh"].get("analyzer") != "ik_max_word"
            or translations["zh"].get("search_analyzer") != "ik_smart"
            or translations["en"].get("analyzer") != "english_no_stop"
            or translations["ja"].get("analyzer") != "kuromoji"):
        raise ValueError("Target meaning analyzers do not match the v4 schema")
    return {"source": source, "target": target, "documents": target_count,
            "schema": SCHEMA, "source_preserved": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="features-v3")
    parser.add_argument("--target", default="features-v4")
    args = parser.parse_args()
    settings = Settings.from_env()
    with connect(settings) as client:
        print(json.dumps(reindex_v4(client, settings, args.source, args.target)))


if __name__ == "__main__":
    main()
