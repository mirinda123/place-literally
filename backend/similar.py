"""Symmetric lexical links: shared-term coarse filtering, then bidirectional fine filtering."""

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from .indexing import PUBLIC_SOURCE_EXCLUDES, SIMILAR_ANALYZERS, SIMILAR_TERMS_VERSION, STOPWORDS_DIR


SimilarLanguage = Literal["zh", "en", "es", "fr", "ja"]
PAGE_SIZE = 200
MIN_LANGUAGE_SUPPORT = 2
# These are analyzer-output tokens, including stems such as citi and villag.
# Post-filtering keeps existing index analyzers unchanged. The indexed terms
# remain a recall superset; fine filtering applies the same vocabulary to both
# meanings. Keep directions, colors, negation, and other content words.
LOW_INFORMATION_TERMS = {lang: frozenset(words) for lang, words in json.loads(
    (STOPWORDS_DIR / "similar_low_information.json").read_text(encoding="utf-8")).items()}


@dataclass(frozen=True)
class LanguageMeaning:
    terms: frozenset[str]
    phrase: str | None = None


class SimilarityIndexNotReady(ValueError):
    pass


class LexicalTermCache:
    """Cache tokenization of text, not city pairs; new/edited texts get fresh cache keys."""

    def __init__(self, client, index: str):
        self.client = client
        self.index = index
        self._ready = False
        self.terms = lru_cache(maxsize=16384)(self._analyze)
        self.phrase = lru_cache(maxsize=16384)(self._normalize_phrase)

    def _analyze(self, language: str, text: str):
        if not self._ready:
            mapping = self.client.indices.get_mapping(index=self.index)[self.index]["mappings"]
            fields = mapping["properties"]["literal_meanings"]["properties"]["translations"].get("properties", {})
            if mapping.get("_meta", {}).get("similar_terms_version") != SIMILAR_TERMS_VERSION or not all(
                fields.get(lang, {}).get("fields", {}).get("similar", {}).get("analyzer") == analyzer
                and fields.get(lang, {}).get("fields", {}).get("raw", {}).get("normalizer") == "name_fold"
                for lang, analyzer in SIMILAR_ANALYZERS.items()
            ):
                raise SimilarityIndexNotReady("Run python -m backend.configure_similarity_fields before lexical search")
            self._ready = True
        analyzed = self.client.indices.analyze(index=self.index, analyzer=SIMILAR_ANALYZERS[language], text=text)
        return frozenset(token["token"] for token in analyzed["tokens"])

    def _normalize_phrase(self, text: str):
        # Use the exact normalizer of .raw so coarse recall and phrase equality
        # agree on case and accents. Preserve word order, punctuation, spacing,
        # and every original word; empty term sets must not match each other.
        analyzed = self.client.indices.analyze(index=self.index, normalizer="name_fold", text=text)
        return analyzed["tokens"][0]["token"] if analyzed["tokens"] else None

    def clear(self):
        self.terms.cache_clear()
        self.phrase.cache_clear()
        self._ready = False


def _meaning_terms(meanings, analyze_terms, normalize_phrase):
    parsed = []
    for meaning in meanings:
        languages = {}
        for lang in SIMILAR_ANALYZERS:
            text = meaning.get("translations", {}).get(lang)
            if not isinstance(text, str) or not text.strip():
                continue
            words = analyze_terms(lang, text.strip()) - LOW_INFORMATION_TERMS[lang]
            # Definitions such as "In the City" still have a complete meaning
            # after content terms run out. Keep the original phrase as a strict
            # fallback, rather than letting a preposition or generic noun vote.
            languages[lang] = LanguageMeaning(words, normalize_phrase(text) if not words else None)
        parsed.append(languages)
    return parsed


def _required_matches(count):
    return count if count <= 2 else (count + 1) // 2


def _pair_score(source, candidate):
    # Fine filtering: intersect deduplicated effective terms for one meaning
    # pair in each language. A->B requires all of A's terms for 1-2 terms,
    # or ceil(n/2) for more. B->A independently uses B's term count.
    # Count language votes separately for each direction; never pool them.
    # Accept either direction with at least two votes. The symmetric score is
    # max(forward_votes, reverse_votes).
    forward = reverse = 0
    for lang in SIMILAR_ANALYZERS:
        left, right = source.get(lang), candidate.get(lang)
        if left is None or right is None:
            continue
        # Weak definitions require equality of their complete normalized
        # phrases, in both directions. "In the City" cannot match "City of
        # water" or "Shelter in the marshes" through a generic word alone.
        if left.phrase or right.phrase:
            if left.phrase and left.phrase == right.phrase:
                forward += 1
                reverse += 1
            continue
        shared = len(left.terms & right.terms)
        if shared:
            forward += shared >= _required_matches(len(left.terms))
            reverse += shared >= _required_matches(len(right.terms))
    score = max(forward, reverse)
    return score if score >= MIN_LANGUAGE_SUPPORT else 0


def _best_pair(source_terms, candidate_terms, source_id, candidate_id):
    best = None
    for source_index, source in enumerate(source_terms):
        for matched_index, candidate in enumerate(candidate_terms):
            score = _pair_score(source, candidate)
            # Evaluate meaning pairs separately; never pool terms or language
            # votes across meanings. Break ties using meaning indices ordered
            # by place ID, so reverse searches select the same pair with its
            # two indices swapped.
            tie = ((source_index, matched_index) if source_id < candidate_id else
                   (matched_index, source_index))
            if score and (best is None or score > best[0] or (score == best[0] and tie < best[1])):
                best = (score, tie, source_index, matched_index)
    return best


def similar_places(client, index: str, origin: dict, lang: SimilarLanguage,
                   page_size: int = PAGE_SIZE, analyze_terms=None, normalize_phrase=None):
    """Return every bidirectionally accepted place, with its best interpretation pair."""
    response = {"feature_id": origin["feature_id"], "lang": lang,
                "threshold": None, "total": 0, "results": []}
    if not origin.get("literal_meanings"):
        return response
    if analyze_terms is None or normalize_phrase is None:
        cache = LexicalTermCache(client, index)
        analyze_terms = analyze_terms or cache.terms
        normalize_phrase = normalize_phrase or cache.phrase
    source_terms = _meaning_terms(origin["literal_meanings"], analyze_terms, normalize_phrase)

    # Coarse filtering: build a nested query for each source meaning. One
    # candidate meaning must have support in two languages: at least one
    # effective term in common, or an equal complete phrase for weak meanings.
    # The terms query uses normalized tokens; .similar's inverted index uses
    # the same analyzer, so reverse-only matches of short meanings are recalled.
    # Two supporting languages are necessary for fine filtering. This stage only
    # gathers candidates; it does not apply a BM25 score threshold.
    queries = []
    for terms in source_terms:
        votes = []
        for language, meaning in terms.items():
            field = f"literal_meanings.translations.{language}"
            if meaning.terms:
                votes.append({"terms": {f"{field}.similar": sorted(meaning.terms)}})
            elif meaning.phrase:
                votes.append({"term": {f"{field}.raw": meaning.phrase}})
        if len(votes) >= MIN_LANGUAGE_SUPPORT:
            queries.append({"nested": {"path": "literal_meanings", "score_mode": "none",
                "query": {"bool": {"should": votes, "minimum_should_match": MIN_LANGUAGE_SUPPORT}}}})
    if not queries:
        return response
    query = {"bool": {"must_not": [{"term": {"feature_id": origin["feature_id"]}}],
                      "filter": [{"bool": {"should": queries, "minimum_should_match": 1}}]}}
    pit = client.open_point_in_time(index=index, keep_alive="1m")["id"]
    try:
        after = None
        while True:
            # Fetch every candidate page; a coarse Top N could miss reverse links.
            found = client.search(query=query, sort=[{"feature_id": "asc"}],
                pit={"id": pit, "keep_alive": "1m"}, size=page_size,
                search_after=after, track_total_hits=False, source_excludes=PUBLIC_SOURCE_EXCLUDES)
            pit = found.get("pit_id", pit)
            hits = found["hits"]["hits"]
            if not hits:
                break
            for hit in hits:
                candidate = hit["_source"]
                candidate_terms = _meaning_terms(candidate.get("literal_meanings", []), analyze_terms, normalize_phrase)
                best = _best_pair(source_terms, candidate_terms, origin["feature_id"], candidate["feature_id"])
                if best:
                    score, _, source_index, matched_index = best
                    response["results"].append({"feature": candidate, "score": score,
                        "source_meaning_index": source_index, "matched_meaning_index": matched_index})
            if len(hits) < page_size:
                break
            after = hits[-1]["sort"]
        response["results"].sort(key=lambda item: (-item["score"], item["feature"]["feature_id"]))
        response["total"] = len(response["results"])
        return response
    finally:
        client.close_point_in_time(id=pit)
