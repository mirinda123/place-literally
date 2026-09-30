"""Exact, symmetric interpretation-level links using precomputed ES vectors."""

from .embed_meanings import validate_vector
from .indexing import EMBEDDING_FIELD, PUBLIC_SOURCE_EXCLUDES
from .similar import PAGE_SIZE, SimilarLanguage


def vector_similar_places(client, index: str, origin: dict, lang: SimilarLanguage,
                          min_similarity: float, page_size: int = PAGE_SIZE):
    """Compare stored vectors and keep the best sense pair above the cosine threshold."""
    response = {"feature_id": origin["feature_id"], "lang": lang, "engine": "vector",
                "min_similarity": min_similarity, "available": False, "total": 0, "results": []}
    source = []
    for source_index, meaning in enumerate(origin.get("literal_meanings") or []):
        text = meaning.get("translations", {}).get(lang)
        vector = meaning.get(EMBEDDING_FIELD, {}).get(lang)
        if isinstance(text, str) and text.strip() and vector is not None:
            source.append((source_index, validate_vector(vector)))
    if not source:
        return response
    response["available"] = True
    field = f"literal_meanings.{EMBEDDING_FIELD}.{lang}"
    script = f"cosineSimilarity(params.vector, '{field}') + 1.0"
    best_by_id = {}
    pit = client.open_point_in_time(index=index, keep_alive="1m")["id"]
    try:
        for source_index, vector in source:
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
