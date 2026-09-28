"""Copy v8 documents into a clean v9 mapping named for qwen3.7-text-embedding."""

import argparse
import json

from .config import Settings, connect
from .indexing import EMBEDDING_FIELD, EMBEDDING_LANGUAGES
from .reindex_search_v5 import reindex_search


OLD_FIELD = "embeddings_qwen3_8b_512_v1"


def reindex_v9(client, settings, source: str, target: str):
    old_mapping = client.indices.get_mapping(index=source)[source]["mappings"]
    old_properties = old_mapping["properties"]["literal_meanings"]["properties"]
    if OLD_FIELD not in old_properties:
        raise ValueError(f"Expected old empty vector field in {source}")
    for lang in EMBEDDING_LANGUAGES:
        count = client.count(index=source, query={"nested": {
            "path": "literal_meanings",
            "query": {"exists": {"field": f"literal_meanings.{OLD_FIELD}.{lang}"}},
        }})["count"]
        if count:
            raise ValueError(f"{count} source documents contain {lang} vectors; migrate them before reindexing")

    report = reindex_search(client, settings, source, target)
    new_mapping = client.indices.get_mapping(index=target)[target]["mappings"]
    properties = new_mapping["properties"]["literal_meanings"]["properties"]
    if OLD_FIELD in properties:
        raise ValueError("The old vector field is still mapped in the target")
    fields = properties[EMBEDDING_FIELD]["properties"]
    for lang in EMBEDDING_LANGUAGES:
        field = fields[lang]
        if field["type"] != "dense_vector" or field["dims"] != 512 or field["similarity"] != "cosine":
            raise ValueError(f"Unexpected {lang} vector mapping: {field}")
    report["vector_field"] = EMBEDDING_FIELD
    report["vector_dimensions"] = 512
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="features-v8")
    parser.add_argument("--target", default="features-v9")
    args = parser.parse_args()
    settings = Settings.from_env()
    with connect(settings) as client:
        print(json.dumps(reindex_v9(client, settings, args.source, args.target), ensure_ascii=False))


if __name__ == "__main__":
    main()
