"""Copy features-v4 into a new index with multilingual similarity analyzers."""

import argparse
import json
from dataclasses import replace

from .config import Settings, connect
from .indexing import SCHEMA, import_seed


def reindex_search(client, settings, source: str, target: str):
    if source == target or client.indices.exists(index=target):
        raise ValueError("The target must be a new index; existing data is never overwritten")
    source_mapping = client.indices.get_mapping(index=source)[source]["mappings"]
    source_meta = source_mapping.get("_meta", {})
    if source_meta.get("schema") != SCHEMA:
        raise ValueError(f"Expected source schema {SCHEMA}")

    target_settings = replace(settings, index=target, analyzer=source_meta["analyzer"])
    import_seed(client, target_settings, [])
    source_settings = client.indices.get_settings(index=source, flat_settings=True, include_defaults=True)[source]
    field_key = "index.mapping.total_fields.limit"
    source_limit = int(source_settings["settings"].get(field_key,
                       source_settings.get("defaults", {}).get(field_key, 1000)))
    client.indices.put_settings(index=target, settings={field_key: max(2000, source_limit + 200)})

    before = client.count(index=source)["count"]
    result = client.options(request_timeout=900).reindex(
        source={"index": source}, dest={"index": target}, refresh=True)
    source_count = client.count(index=source)["count"]
    target_count = client.count(index=target)["count"]
    if (result.get("failures") or result.get("version_conflicts")
            or result["created"] != before or source_count != before or target_count != before):
        raise ValueError(f"Reindex incomplete: before={before}, source={source_count}, "
                         f"target={target_count}, created={result.get('created')}, "
                         f"failures={result.get('failures')}")
    for feature_id in ("china-cn", "nanjing-cn", "new-york-us", "osm-node-424312026"):
        if (client.get(index=source, id=feature_id)["_source"]
                != client.get(index=target, id=feature_id)["_source"]):
            raise ValueError(f"Source document changed in {feature_id}")
    tokens = {lang: [item["token"] for item in client.indices.analyze(
        index=target, analyzer=analyzer, text=text)["tokens"]]
        for lang, analyzer, text in (
            ("zh", "similar_zh_v2", "中央之国"),
            ("en", "similar_en_v2", "central country"),
            ("fr", "similar_fr_v2", "pays du centre"),
            ("es", "similar_es_v2", "país del centro"))}
    if not all(len(value) == 1 for value in tokens.values()):
        raise ValueError(f"Generic country terms were not removed: {tokens}")
    return {"source": source, "target": target, "documents": target_count,
            "schema": SCHEMA, "source_preserved": True, "query_tokens": tokens}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="features-v4")
    parser.add_argument("--target", default="features-v5")
    args = parser.parse_args()
    settings = Settings.from_env()
    with connect(settings) as client:
        print(json.dumps(reindex_search(client, settings, args.source, args.target),
                         ensure_ascii=False))


if __name__ == "__main__":
    main()
