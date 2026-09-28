"""Exact, interpretation-level vector links for the small embedding pilot."""

import os
from threading import Lock

from .config import ROOT
from .embed_meanings import (DEFAULT_ENDPOINT, DEFAULT_INSTRUCT, DIMENSIONS,
                             EmbeddingClient, validate_vector)
from .indexing import EMBEDDING_FIELD, PUBLIC_SOURCE_EXCLUDES
from .similar import PAGE_SIZE, SimilarLanguage


class QueryEmbeddingService:
    """Share the query cache safely across FastAPI's worker threads."""

    def __init__(self):
        self._client = EmbeddingClient(
            ROOT / "work" / "vector-query-cache",
            os.getenv("DASHSCOPE_EMBEDDING_URL", DEFAULT_ENDPOINT),
            DEFAULT_INSTRUCT, batch_size=20)
        self._lock = Lock()

    def embed(self, texts: list[str]) -> dict[str, list[float]]:
        with self._lock:
            return self._client.embed(texts, "query")


def vector_similar_places(client, index: str, origin: dict, lang: SimilarLanguage,
                          min_similarity: float, embed_queries, page_size: int = PAGE_SIZE):
    """Return every place above the raw cosine threshold, using one sense at a time."""
    response = {"feature_id": origin["feature_id"], "lang": lang, "engine": "vector",
                "min_similarity": min_similarity, "available": False, "total": 0, "results": []}
    source = []
    for source_index, meaning in enumerate(origin.get("literal_meanings") or []):
        text = meaning.get("translations", {}).get(lang)
        vector = meaning.get(EMBEDDING_FIELD, {}).get(lang)
        if isinstance(text, str) and text.strip() and vector is not None:
            validate_vector(vector)
            source.append((source_index, text))
    if not source:
        return response
    response["available"] = True
    vectors = embed_queries([text for _, text in source])
    field = f"literal_meanings.{EMBEDDING_FIELD}.{lang}"
    script = f"cosineSimilarity(params.vector, '{field}') + 1.0"
    best_by_id = {}
    pit = client.open_point_in_time(index=index, keep_alive="1m")["id"]
    try:
        for source_index, text in source:
            vector = vectors[text]
            if len(vector) != DIMENSIONS:
                raise ValueError("Query embedding dimensions do not match the index")
            query = {"bool": {
                "must_not": [{"term": {"feature_id": origin["feature_id"]}}],
                "must": [{"nested": {"path": "literal_meanings", "score_mode": "max",
                    "query": {"script_score": {
                        "query": {"exists": {"field": field}},
                        "script": {"source": script, "params": {"vector": vector}}}},
                    "inner_hits": {"name": "matched", "size": 1, "_source": False}}}],
            }}
            after = None
            while True:
                found = client.search(
                    query=query, pit={"id": pit, "keep_alive": "1m"},
                    size=page_size, min_score=1.0 + min_similarity,
                    sort=[{"_score": "desc"}, {"feature_id": "asc"}],
                    search_after=after, track_total_hits=False,
                    source_excludes=PUBLIC_SOURCE_EXCLUDES)
                pit = found.get("pit_id", pit)
                hits = found["hits"]["hits"]
                if not hits:
                    break
                for hit in hits:
                    nested = hit["inner_hits"]["matched"]["hits"]["hits"][0]
                    feature = hit["_source"]
                    feature_id = feature["feature_id"]
                    cosine = hit["_score"] - 1.0
                    previous = best_by_id.get(feature_id)
                    if previous is None or cosine > previous["raw_score"]:
                        best_by_id[feature_id] = {
                            "feature": feature, "raw_score": cosine,
                            "source_meaning_index": source_index,
                            "matched_meaning_index": nested["_nested"]["offset"]}
                if len(hits) < page_size:
                    break
                after = hits[-1]["sort"]
    finally:
        client.close_point_in_time(id=pit)
    ordered = sorted(best_by_id.values(),
                     key=lambda item: (-item["raw_score"], item["feature"]["feature_id"]))
    response["results"] = [{"feature": item["feature"], "score": round(item["raw_score"], 4),
                            "source_meaning_index": item["source_meaning_index"],
                            "matched_meaning_index": item["matched_meaning_index"]}
                           for item in ordered]
    response["total"] = len(ordered)
    return response
