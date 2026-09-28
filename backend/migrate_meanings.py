"""Copy v1 feature documents into the list-based current index without deleting v1."""
import argparse
import json
from dataclasses import replace

from elasticsearch import helpers

from .config import Settings, connect
from .indexing import Feature, SCHEMA, import_seed


def convert_document(doc):
    converted = {**doc}
    old = doc.get("literal_meanings") or {}
    if not isinstance(old, dict):
        raise ValueError(f"Expected v1 meanings for {doc['feature_id']}")
    converted["literal_meanings"] = [{"translations": old}] if old else []
    return Feature.model_validate(converted).model_dump()


def migrate(client, source, target, settings):
    if target in {"features-v1", "features-v2", "features-v3"}:
        raise ValueError("A legacy index name cannot receive the current v4 schema")
    source_meta = client.indices.get_mapping(index=source)[source]["mappings"].get("_meta", {})
    if source_meta.get("schema") != "literal-name-map-features-v1":
        raise ValueError("Source is not the v1 features index")
    if source == target or client.indices.exists(index=target):
        raise ValueError("Destination must be a new index; existing indices are never overwritten")
    target_settings = replace(settings, index=target, analyzer=source_meta["analyzer"])
    import_seed(client, target_settings, [])
    source_settings = client.indices.get_settings(index=source, flat_settings=True, include_defaults=True)[source]
    field_key = "index.mapping.total_fields.limit"
    source_limit = int(source_settings["settings"].get(field_key,
                       source_settings.get("defaults", {}).get(field_key, 1000)))
    client.indices.put_settings(index=target, settings={field_key: max(2000, source_limit + 200)})
    def actions():
        for hit in helpers.scan(client, index=source, query={"query": {"match_all": {}}}):
            doc = convert_document(hit["_source"])
            yield {"_index": target, "_id": hit["_id"], "_source": doc}
    count, _ = helpers.bulk(client, actions(), chunk_size=400, refresh="wait_for")
    expected = client.count(index=source)["count"]
    actual = client.count(index=target)["count"]
    if count != expected or actual != expected:
        raise ValueError(f"Migration count mismatch: source={expected}, copied={count}, target={actual}")
    return {"source": source, "destination": target, "documents": actual,
            "schema": SCHEMA, "source_preserved": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="features-v1")
    parser.add_argument("--target", default="features-v4")
    args = parser.parse_args()
    settings = Settings.from_env()
    with connect(settings) as client:
        print(json.dumps(migrate(client, args.source, args.target, settings)))


if __name__ == "__main__":
    main()
