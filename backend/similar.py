"""Equal-weight, multilingual lexical evidence for interpretation-level links."""

from typing import Literal

from .indexing import PUBLIC_SOURCE_EXCLUDES


SimilarLanguage = Literal["zh", "en", "es", "fr", "ja"]
PAGE_SIZE = 200
# ES applies the per-language analyzers and counts matching language clauses.
# A single candidate interpretation must have at least two language votes.
# Per-language match: require all terms for one/two-token meanings; for longer
# meanings allow up to half the analyzed terms to be absent. ES still requires
# one term when analysis leaves just one.
MIN_LANGUAGE_SUPPORT = 2
MIN_TERMS_PER_LANGUAGE = "2<-50%"
SIMILAR_ANALYZERS: dict[SimilarLanguage, str] = {
    "zh": "similar_zh_v3", "en": "similar_en_v3", "ja": "similar_ja_v3",
    "fr": "similar_fr_v3", "es": "similar_es_v3",
}


def _best_interpretation(hit, source_count):
    best = None
    for source_index in range(source_count):
        nested = hit.get("inner_hits", {}).get(f"source_{source_index}", {}).get("hits", {}).get("hits", [])
        if not nested:
            continue
        candidate = nested[0]
        score = candidate.get("_score") or 0
        if best is None or score > best[0]:
            best = (score, source_index, candidate["_nested"]["offset"])
    return best


def similar_places(client, index: str, origin: dict, lang: SimilarLanguage, page_size: int = PAGE_SIZE):
    """Require two language votes, each using a length-aware term threshold.

    A PIT keeps score/order stable while search_after walks all matching places.
    Separate nested queries prevent unrelated interpretations adding up to a match.
    """
    response = {"feature_id": origin["feature_id"], "lang": lang,
                "threshold": None, "total": 0, "results": []}
    if not origin.get("literal_meanings"):
        return response

    queries = []
    for source_index, item in enumerate(origin["literal_meanings"]):
        votes = []
        for language, analyzer in SIMILAR_ANALYZERS.items():
            meaning = item.get("translations", {}).get(language, "").strip()
            if not meaning:
                continue
            field = f"literal_meanings.translations.{language}"
            votes.append({"constant_score": {"filter": {"match": {field: {
                "query": meaning, "analyzer": analyzer, "operator": "or",
                "minimum_should_match": MIN_TERMS_PER_LANGUAGE,
                "zero_terms_query": "none",
            }}}, "boost": 1}})
        if len(votes) < MIN_LANGUAGE_SUPPORT:
            continue
        queries.append({"nested": {"path": "literal_meanings", "score_mode": "max",
            "query": {"bool": {"should": votes,
                                "minimum_should_match": MIN_LANGUAGE_SUPPORT}},
            "inner_hits": {"name": f"source_{source_index}", "size": 1,
                           "_source": False}}})
    if not queries:
        return response
    query = {"bool": {
        "must_not": [{"term": {"feature_id": origin["feature_id"]}}],
        "must": [{"dis_max": {"tie_breaker": 0, "queries": queries}}],
    }}
    pit = client.open_point_in_time(index=index, keep_alive="1m")["id"]
    try:
        common = {"query": query, "sort": [{"_score": "desc"}, {"feature_id": "asc"}],
                  "pit": {"id": pit, "keep_alive": "1m"}}
        after = None
        while True:
            found = client.search(**{**common, "pit": {"id": pit, "keep_alive": "1m"}},
                                  size=page_size,
                                  search_after=after, track_total_hits=False,
                                  source_excludes=PUBLIC_SOURCE_EXCLUDES)
            pit = found.get("pit_id", pit)
            hits = found["hits"]["hits"]
            if not hits:
                break
            for hit in hits:
                matched = _best_interpretation(hit, len(origin.get("literal_meanings", [])))
                if matched is None:
                    continue
                _, source_index, matched_index = matched
                response["results"].append({"feature": hit["_source"], "score": hit["_score"],
                                            "source_meaning_index": source_index,
                                            "matched_meaning_index": matched_index})
            if len(hits) < page_size:
                break
            after = hits[-1]["sort"]
        response["total"] = len(response["results"])
        return response
    finally:
        client.close_point_in_time(id=pit)
