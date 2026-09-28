"""Reindex v2 features into the current analyzer schema, preserving the source index."""
import argparse
import json
from dataclasses import replace

from .config import Settings, connect
from .indexing import SCHEMA, import_seed


def reindex_ik(client, settings, source, target):
    if target in {"features-v1", "features-v2", "features-v3"}:
        raise ValueError("A legacy index name cannot receive the current v4 schema")
    if source == target or client.indices.exists(index=target):
        raise ValueError("The target must be a new index; existing data is never overwritten")
    source_mapping = client.indices.get_mapping(index=source)[source]["mappings"]
    source_meta = source_mapping.get("_meta", {})
    if source_meta.get("schema") != "literal-name-map-features-v2":
        raise ValueError("The source must be the v2 features index")

    target_settings = replace(settings, index=target, analyzer=source_meta["analyzer"])
    import_seed(client, target_settings, [])
    source_settings = client.indices.get_settings(index=source, flat_settings=True, include_defaults=True)[source]
    field_key = "index.mapping.total_fields.limit"
    source_limit = int(source_settings["settings"].get(field_key,
                       source_settings.get("defaults", {}).get(field_key, 1000)))
    client.indices.put_settings(index=target, settings={field_key: max(2000, source_limit + 200)})

    result = client.options(request_timeout=900).reindex(
        source={"index": source}, dest={"index": target}, refresh=True)
    source_count = client.count(index=source)["count"]
    target_count = client.count(index=target)["count"]
    if result.get("failures") or result.get("version_conflicts") or result["created"] != source_count or target_count != source_count:
        raise ValueError(f"Reindex incomplete: source={source_count}, target={target_count}, "
                         f"created={result.get('created')}, failures={result.get('failures')}")
    mapping = client.indices.get_mapping(index=target)[target]["mappings"]
    zh = mapping["properties"]["literal_meanings"]["properties"]["translations"]["properties"]["zh"]
    if (mapping.get("_meta", {}).get("schema") != SCHEMA
            or zh.get("analyzer") != "ik_max_word" or zh.get("search_analyzer") != "ik_smart"):
        raise ValueError("Target Chinese meaning mapping was not created with IK")
    return {"source": source, "target": target, "documents": target_count,
            "zh_analyzer": zh["analyzer"], "zh_search_analyzer": zh["search_analyzer"],
            "source_preserved": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="features-v2")
    parser.add_argument("--target", default="features-v4")
    args = parser.parse_args()
    settings = Settings.from_env()
    with connect(settings) as client:
        print(json.dumps(reindex_ik(client, settings, args.source, args.target)))


if __name__ == "__main__":
    main()
