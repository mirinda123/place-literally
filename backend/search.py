"""ES lexical retrieval with explicit concept constraints; no generated vectors."""
import re
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .indexing import PUBLIC_SOURCE_EXCLUDES, normalize
from .config import ROOT
GROUPS = json.loads((ROOT / "data" / "meaning-groups.json").read_text(encoding="utf-8"))

VOCABULARY = {
    "new": ["新", "new", "newly", "fresh"],
    "settlement": ["城", "城市", "城镇", "定居点", "city", "cities", "town", "towns", "settlement", "settlements"],
    "capital": ["首都", "都城", "京城", "capital", "capitals", "seat of government"],
    "central": ["中央", "中心", "central", "center", "centre", "middle"],
    "north": ["北", "north", "northern"], "south": ["南", "south", "southern"],
    "east": ["东", "東", "east", "eastern"], "west": ["西", "west", "western"],
    "white": ["白", "white"], "black": ["黑", "black"],
    "country": ["国家", "国度", "country", "state", "kingdom"],
    "water": ["水", "河", "海", "water", "river", "rivers", "sea", "ocean"],
    "mountain": ["山", "mountain", "mountains", "hill"],
    "old": ["旧", "老城", "old", "ancient"],
}


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=200)
    scope: Literal["exact", "near", "theme"] = "near"
    limit: int = Field(default=12, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=9900)
    kind: str | None = Field(default=None, max_length=40)
    meaning_id: str | None = Field(default=None, max_length=100)


def query_concepts(query):
    q = normalize(query)
    return [concept for concept, words in VOCABULARY.items() if any(
        word in q if re.search(r"[\u3400-\u9fff]", word) else f" {word} " in f" {q} "
        for word in words)]


def group_query(concepts, scope):
    def matches(entry):
        present = set(entry["concept_ids"])
        if "capital" in present:
            present.add("settlement")
        if scope == "theme" and concepts == ["central"]:
            return "centrality" in entry["cluster_ids"]
        if scope == "exact" and concepts == ["capital"]:
            return entry["concept_ids"] == ["capital"]
        return set(concepts).issubset(present)
    meaning_ids = [key for key, entry in GROUPS["meanings"].items() if matches(entry)]
    feature_ids = [key for key, entry in GROUPS["overrides"].items() if matches(entry)]
    return {"bool": {"should": [{"terms": {"meaning_id": meaning_ids}},
                                {"terms": {"feature_id": feature_ids}}], "minimum_should_match": 1}}


def build_query(request, meaning_fields):
    concepts = query_concepts(request.query)
    def meaning_query(field, boost, name, **options):
        fields = [f"literal_meanings.translations.*{field}"] if field else meaning_fields
        if not fields:
            return {"match_none": {}}
        return {"nested": {"path": "literal_meanings", "score_mode": "max",
            "query": {"multi_match": {"query": request.query,
                "fields": fields,
                "boost": boost, **options}}, "_name": name}}
    should = [
        {"multi_match": {"query": request.query, "fields": ["search_names.raw", "literal_name.text.raw"],
                         "boost": 100, "_name": "exact_name"}},
        meaning_query(".raw", 20, "exact_meaning"),
    ]
    # Chinese users commonly omit the administrative city suffix (U+5E02). Prefer the
    # complete city name over a longer unrelated label containing the query.
    if re.fullmatch(r"[\u3400-\u9fff]{2,12}", request.query) and not request.query.endswith("市"):
        should.append({"constant_score": {"filter": {"term": {"search_names.raw": request.query + "市"}},
                                          "boost": 120, "_name": "city_name_with_suffix"}})
    if request.scope != "exact":
        if not concepts:
            should.append({"multi_match": {"query": request.query,
                "fields": ["search_names", "literal_name.text"], "type": "phrase", "boost": 5, "_name": "name"}})
        should.append(meaning_query("", 1, "text", operator="and"))
    if concepts:
        # Exact groups require a complete concept combination, except the explicit
        # capital/settlement hierarchy. Near/theme scopes can include modifiers.
        if request.scope != "exact" or concepts == ["capital"]:
            should.append({"constant_score": {"filter": group_query(concepts, request.scope),
                                               "boost": 8, "_name": "group"}})
        else:
            exact_ids = [key for key, entry in GROUPS["meanings"].items()
                         if set(entry["concept_ids"]) == set(concepts)]
            if exact_ids:
                should.append({"terms": {"meaning_id": exact_ids, "_name": "group"}})
    filters = [{"term": {key: value}} for key, value in (
        ("kind", request.kind), ("meaning_id", request.meaning_id)) if value]
    return {"bool": {"filter": filters, "should": should, "minimum_should_match": 1}}


def run_search(client, settings, request):
    response = {"query": request.query, "scope": request.scope, "engine": "elasticsearch",
                "results": [], "total": 0, "offset": request.offset, "limit": request.limit}
    if re.search(r"不要|不含|没有|不是|without|\bnot\b", request.query, re.I):
        response["notice"] = "当前暂不解析否定条件，请使用正向含义描述。"
        return response
    meaning_fields = []
    if request.scope != "exact":
        capabilities = client.field_caps(index=settings.index, fields=["literal_meanings.translations.*"])
        # Ordinary search explicitly uses the original translation fields and
        # .raw. Wildcards must not pull in .similar's different stop-word rules.
        # Read mapped languages so new ones need no hardcoding or API restart.
        meaning_fields = sorted(field for field in capabilities["fields"]
                                if field.count(".") == 2 or field.endswith(".raw"))
    found = client.search(index=settings.index, query=build_query(request, meaning_fields), size=request.limit,
                          from_=request.offset, track_total_hits=True,
                          sort=[{"_score": "desc"}, {"feature_id": "asc"}],
                          source_excludes=PUBLIC_SOURCE_EXCLUDES)
    for hit in found["hits"]["hits"]:
        doc = hit["_source"]
        matches = hit.get("matched_queries", [])
        is_name = "exact_name" in matches or "city_name_with_suffix" in matches or "name" in matches
        response["results"].append({
            **doc, "match_kind": "name" if is_name else "meaning",
            "reason": "名称匹配" if is_name else "字面含义匹配",
            "score": hit["_score"],
        })
    response.update(total=found["hits"]["total"]["value"], took_ms=found["took"])
    return response
