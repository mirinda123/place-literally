"""Add five 512-dimensional vector fields to each nested literal meaning."""

import json

from .config import Settings, connect
from .indexing import EMBEDDING_FIELD, EMBEDDING_LANGUAGES, index_mapping


def add_mapping(client, settings):
    desired = index_mapping(settings.analyzer)["properties"]["literal_meanings"]
    vectors = desired["properties"][EMBEDDING_FIELD]
    before = client.indices.get_mapping(index=settings.index)[settings.index]["mappings"]
    meaning = before["properties"]["literal_meanings"]
    if meaning["type"] != "nested":
        raise ValueError("literal_meanings must remain nested")
    if EMBEDDING_FIELD not in meaning.get("properties", {}):
        client.indices.put_mapping(index=settings.index, properties={
            "literal_meanings": {"type": "nested", "properties": {EMBEDDING_FIELD: vectors}}
        })
    after = client.indices.get_mapping(index=settings.index)[settings.index]["mappings"]
    actual = after["properties"]["literal_meanings"]["properties"][EMBEDDING_FIELD]
    for lang in EMBEDDING_LANGUAGES:
        field = actual["properties"][lang]
        if field["type"] != "dense_vector" or field["dims"] != 512 or field.get("similarity") != "cosine":
            raise ValueError(f"Unexpected vector mapping for {lang}: {field}")
    return {"index": settings.index, "field": EMBEDDING_FIELD,
            "languages": list(EMBEDDING_LANGUAGES), "dims": 512,
            "root_documents": client.count(index=settings.index)["count"]}


def main():
    settings = Settings.from_env()
    with connect(settings) as client:
        print(json.dumps(add_mapping(client, settings)))


if __name__ == "__main__":
    main()
