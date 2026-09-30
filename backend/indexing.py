"""Import feature documents and their external identities into one ES index."""
import argparse
import json
import math
import re
import unicodedata
from pathlib import Path

from elasticsearch import helpers
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .config import ROOT, Settings, connect

SCHEMA = "literal-name-map-features-v4"
EMBEDDING_FIELD = "embeddings_qwen3_7_text_embedding_512_v1"
EMBEDDING_LANGUAGES = ("zh", "en", "ja", "fr", "es")
PUBLIC_SOURCE_EXCLUDES = [f"literal_meanings.{EMBEDDING_FIELD}"]
SIMILAR_TERMS_VERSION = 1
SIMILAR_ANALYZERS = {lang: f"similar_{lang}_v3" for lang in EMBEDDING_LANGUAGES}

# /similar uses these analyzers for both its dedicated .similar subfields and
# request-side token sets. Ordinary search keeps the original field analyzers.
STOPWORDS_DIR = Path(__file__).resolve().parent / "stopwords"


def similar_stopwords(language: str) -> list[str]:
    """Read the versioned /similar vocabulary before creating an ES index."""
    return [line.strip() for line in (STOPWORDS_DIR / f"similar_{language}.txt")
            .read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


SIMILAR_ANALYSIS = {
    "filter": {
        "similar_zh_stop": {"type": "stop", "stopwords": ["的", "之"]},
        "similar_fr_stop": {"type": "stop", "stopwords": ["de", "du", "des", "le", "la", "les"]},
        "similar_es_stop": {"type": "stop", "stopwords": ["de", "del", "el", "la", "los", "las"]},
        "similar_zh_stop_v2": {"type": "stop", "stopwords": ["的", "之", "之国"]},
        "similar_fr_stop_v2": {"type": "stop", "stopwords": ["de", "du", "des", "le", "la", "les", "pays"]},
        "similar_es_stop_v2": {"type": "stop", "stopwords": ["de", "del", "el", "la", "los", "las", "país"]},
        "similar_zh_stop_v3": {"type": "stop", "stopwords": similar_stopwords("zh")},
        "similar_fr_stop_v3": {"type": "stop", "stopwords": similar_stopwords("fr")},
        "similar_es_stop_v3": {"type": "stop", "stopwords": similar_stopwords("es")},
        "similar_ja_stop_v3": {"type": "ja_stop", "stopwords": similar_stopwords("ja")},
    },
    "analyzer": {
        "similar_zh": {"type": "custom", "tokenizer": "ik_smart", "filter": ["similar_zh_stop"]},
        "similar_en": {"type": "english", "stopwords": ["of", "the"]},
        "similar_fr": {"type": "custom", "tokenizer": "standard", "filter": ["lowercase", "similar_fr_stop"]},
        "similar_es": {"type": "custom", "tokenizer": "standard", "filter": ["lowercase", "similar_es_stop"]},
        "similar_zh_v2": {"type": "custom", "tokenizer": "ik_smart", "filter": ["similar_zh_stop_v2"]},
        "similar_en_v2": {"type": "english", "stopwords": ["of", "the", "country"]},
        "similar_fr_v2": {"type": "custom", "tokenizer": "standard", "filter": ["lowercase", "similar_fr_stop_v2"]},
        "similar_es_v2": {"type": "custom", "tokenizer": "standard", "filter": ["lowercase", "similar_es_stop_v2"]},
        "similar_zh_v3": {"type": "custom", "tokenizer": "ik_smart", "filter": ["similar_zh_stop_v3"]},
        "similar_en_v3": {"type": "english", "stopwords": similar_stopwords("en")},
        "similar_ja_v3": {"type": "custom", "tokenizer": "kuromoji_tokenizer",
                          "filter": ["kuromoji_baseform", "kuromoji_part_of_speech",
                                     "cjk_width", "similar_ja_stop_v3", "kuromoji_stemmer", "lowercase"]},
        "similar_fr_v3": {"type": "custom", "tokenizer": "standard", "filter": ["lowercase", "similar_fr_stop_v3"]},
        "similar_es_v3": {"type": "custom", "tokenizer": "standard", "filter": ["lowercase", "similar_es_stop_v3"]},
    },
}


def normalize(value):
    value = unicodedata.normalize("NFKD", value).casefold()
    return " ".join("".join(c if c.isalnum() or c.isspace() else " "
                           for c in value if not unicodedata.combining(c)).split())


class Location(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    lon: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)


class LiteralName(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=500)
    lang: str = Field(pattern=r"^[a-zA-Z]{2,8}(?:-[a-zA-Z0-9]{1,8})*$")


class ExternalIds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    osm: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_osm(self):
        if any(not re.fullmatch(r"(?:node|way|relation)/[1-9][0-9]{0,18}", value) for value in self.osm):
            raise ValueError("OSM IDs must include the object type, e.g. node/244081381")
        if len(set(self.osm)) != len(self.osm):
            raise ValueError("Duplicate OSM IDs")
        return self


class LiteralMeaning(BaseModel):
    model_config = ConfigDict(extra="forbid")
    translations: dict[str, str]
    embeddings_qwen3_7_text_embedding_512_v1: dict[str, list[float]] = Field(
        default_factory=dict, exclude_if=lambda vectors: not vectors)

    @model_validator(mode="after")
    def validate_translations(self):
        if not self.translations:
            raise ValueError("Each interpretation needs a translation")
        for lang, value in self.translations.items():
            if not re.fullmatch(r"[a-zA-Z]{2,8}(?:-[a-zA-Z0-9]{1,8})*", lang):
                raise ValueError("Invalid language tag")
            if not value.strip() or len(value) > 300 or "\n" in value or "\r" in value:
                raise ValueError("Literal meanings must be short, nonempty, single-line strings")
        for lang, vector in self.embeddings_qwen3_7_text_embedding_512_v1.items():
            if lang not in EMBEDDING_LANGUAGES or lang not in self.translations:
                raise ValueError("Embedding language must match a supported translation")
            if len(vector) != 512 or not all(math.isfinite(value) for value in vector):
                raise ValueError("Embeddings must have 512 finite values")
        return self


class Feature(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    feature_id: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=40)
    names: dict[str, str]
    location: Location
    literal_name: LiteralName | None = None
    literal_meanings: list[LiteralMeaning] = Field(default_factory=list, max_length=3)
    meaning_id: str | None = Field(default=None, min_length=1, max_length=100)
    external_ids: ExternalIds = Field(default_factory=ExternalIds)

    @model_validator(mode="after")
    def validate_texts(self):
        if not self.names:
            raise ValueError("At least one display name is required")
        for lang, text in self.names.items():
            if not re.fullmatch(r"[a-zA-Z]{2,8}(?:-[a-zA-Z0-9]{1,8})*", lang):
                raise ValueError("Invalid language tag")
            if not text.strip() or len(text) > 2000:
                raise ValueError("Names must be nonempty short strings")
        if self.literal_meanings and not self.literal_name:
            raise ValueError("Specify which name the literal meanings translate")
        if self.meaning_id and not self.literal_meanings:
            raise ValueError("A meaning group requires a literal meaning")
        return self


def documents(features):
    return [Feature.model_validate(item).model_dump() for item in features]


def index_mapping(analyzer):
    def text(kind, search_analyzer=None):
        mapping = {"type": "text", "analyzer": kind,
                   "fields": {"raw": {"type": "keyword", "normalizer": "name_fold", "ignore_above": 2048}}}
        if search_analyzer:
            mapping["search_analyzer"] = search_analyzer
        return mapping
    def name_text(kind):
        return {**text(kind), "copy_to": "search_names"}
    def similar_text(lang, kind, search_analyzer=None):
        field = text(kind, search_analyzer)
        # Dedicated similarity subfields use the same analyzer and stop words
        # for indexing and queries, making shared-term sets symmetric without
        # changing the original full-text fields or business _source.
        field["fields"]["similar"] = {"type": "text", "analyzer": SIMILAR_ANALYZERS[lang]}
        return field
    return {
        "_meta": {"schema": SCHEMA, "analyzer": analyzer,
                  "zh_meaning_analyzer": "ik_max_word", "zh_meaning_search_analyzer": "ik_smart",
                  "en_meaning_analyzer": "english_no_stop", "ja_meaning_analyzer": "kuromoji",
                  "similar_terms_version": SIMILAR_TERMS_VERSION},
        "dynamic": "strict",
        "dynamic_templates": [
            {"chinese_names": {"path_match": "names.zh*", "match_mapping_type": "string", "mapping": name_text(analyzer)}},
            {"names": {"path_match": "names.*", "match_mapping_type": "string", "mapping": name_text("standard")}},
            {"chinese_meanings": {"path_match": "literal_meanings.translations.zh", "match_mapping_type": "string",
                                  "mapping": text("ik_max_word", "ik_smart")}},
            {"english_meanings": {"path_match": ["literal_meanings.translations.en", "literal_meanings.translations.en-*"], "match_mapping_type": "string", "mapping": text("english_no_stop")}},
            {"japanese_meanings": {"path_match": ["literal_meanings.translations.ja", "literal_meanings.translations.ja-*"], "match_mapping_type": "string", "mapping": text("kuromoji")}},
            {"language_text": {"path_match": ["names.*", "literal_meanings.translations.*"], "match_mapping_type": "string", "mapping": text("standard")}},
        ],
        "properties": {
            "feature_id": {"type": "keyword"}, "kind": {"type": "keyword"},
            "names": {"type": "object", "dynamic": True},
            "search_names": text(analyzer),
            "location": {"type": "geo_point"},
            "literal_name": {"type": "object", "dynamic": "strict", "properties": {
                "text": text(analyzer), "lang": {"type": "keyword"}}},
            "literal_meanings": {"type": "nested", "dynamic": "strict", "properties": {
                "translations": {"type": "object", "dynamic": True, "properties": {
                    "zh": similar_text("zh", "ik_max_word", "ik_smart"),
                    "en": similar_text("en", "english_no_stop"),
                    "ja": similar_text("ja", "kuromoji"),
                    "fr": similar_text("fr", "standard"),
                    "es": similar_text("es", "standard"),
                }},
                EMBEDDING_FIELD: {"type": "object", "dynamic": "strict", "properties": {
                    lang: {"type": "dense_vector", "dims": 512, "index": True, "similarity": "cosine"}
                    for lang in EMBEDDING_LANGUAGES}},
            }},
            "meaning_id": {"type": "keyword"},
            "external_ids": {"type": "object", "dynamic": "strict", "properties": {
                "osm": {"type": "keyword"}}},
        },
    }


def index_settings():
    return {
        "number_of_shards": 1, "number_of_replicas": 0,
        "analysis": {
            "normalizer": {"name_fold": {
                "type": "custom", "filter": ["lowercase", "asciifolding"]}},
            "filter": SIMILAR_ANALYSIS["filter"],
            "analyzer": {"english_no_stop": {
                "type": "english", "stopwords": "_none_"},
                **SIMILAR_ANALYSIS["analyzer"]},
        },
    }


def ensure_name_search(client, settings):
    """Add a copy_to search field without changing feature _source documents."""
    current = client.indices.get_mapping(index=settings.index)[settings.index]["mappings"]
    desired = index_mapping(settings.analyzer)
    changes = {lang: {**field, "copy_to": "search_names"}
               for lang, field in current["properties"]["names"].get("properties", {}).items()
               if field.get("copy_to") not in ("search_names", ["search_names"])}
    client.indices.put_mapping(index=settings.index,
        dynamic_templates=desired["dynamic_templates"],
        properties={"search_names": desired["properties"]["search_names"],
                    "names": {"properties": changes}})
    # Reindex old source values so copy_to applies; retry any unfinished migration.
    missing = {"bool": {"must_not": [{"exists": {"field": "search_names"}}]}}
    query = {"match_all": {}} if changes else missing
    if changes or client.count(index=settings.index, query=missing)["count"]:
        result = client.options(request_timeout=120).update_by_query(index=settings.index,
            query=query, conflicts="proceed", refresh=True)
        if result.get("failures") or result.get("version_conflicts"):
            raise ValueError("Name search migration needs retry; concurrent writes or indexing failures occurred")


def ensure_similarity_fields(client, index: str):
    """Backfill additive similarity subfields; never change meaning text or generate vectors."""
    mapping = client.indices.get_mapping(index=index)[index]["mappings"]
    meta = mapping.get("_meta", {})
    fields = mapping["properties"]["literal_meanings"]["properties"]["translations"].get("properties", {})
    ready = all(fields.get(lang, {}).get("fields", {}).get("similar", {}).get("analyzer") == analyzer
                for lang, analyzer in SIMILAR_ANALYZERS.items())
    if ready and meta.get("similar_terms_version") == SIMILAR_TERMS_VERSION:
        return {"index": index, "action": "already_configured", "updated": 0}
    desired = index_mapping(meta.get("analyzer", "cjk"))["properties"]["literal_meanings"]["properties"]["translations"]["properties"]
    additions = {}
    for lang, analyzer in SIMILAR_ANALYZERS.items():
        field = fields.get(lang, desired[lang])
        existing = field.get("fields", {}).get("similar")
        if existing and existing.get("analyzer") != analyzer:
            raise ValueError(f"The {lang} similarity field uses another analyzer; use a new index")
        additions[lang] = {**field, "fields": {**field.get("fields", {}), "similar": desired[lang]["fields"]["similar"]}}
    client.indices.put_mapping(index=index, properties={"literal_meanings": {"type": "nested", "properties": {
        "translations": {"type": "object", "properties": additions}}}})
    # Adding multi-fields does not populate their inverted index for old docs.
    # A script-free update_by_query reindexes existing content. Mark it ready
    # only after success; interruptions or concurrent-write conflicts can retry.
    eligible = {"bool": {"should": [{"exists": {"field": f"literal_meanings.translations.{lang}"}}
                                     for lang in SIMILAR_ANALYZERS], "minimum_should_match": 1}}
    result = client.options(request_timeout=120).update_by_query(index=index,
        query={"nested": {"path": "literal_meanings", "query": eligible}},
        scroll_size=200, conflicts="abort", refresh=True)
    if result.get("failures") or result.get("version_conflicts") or result.get("timed_out"):
        raise ValueError("Similarity field migration needs retry; concurrent writes or indexing failures occurred")
    client.indices.put_mapping(index=index, meta={**meta, "similar_terms_version": SIMILAR_TERMS_VERSION})
    return {"index": index, "action": "configured", "updated": result["updated"]}


def import_seed(client, settings, features):
    docs = documents(features)
    if len({d["feature_id"] for d in docs}) != len(docs):
        raise ValueError("Duplicate feature IDs")
    mapping = index_mapping(settings.analyzer)
    client.indices.analyze(analyzer=settings.analyzer, text="南方的都城")
    client.indices.analyze(analyzer="ik_max_word", text="南方的都城")
    client.indices.analyze(analyzer="kuromoji", text="新しい町")
    if client.indices.exists(index=settings.index):
        current = client.indices.get_mapping(index=settings.index)[settings.index]["mappings"]
        current_meta = {key: value for key, value in current.get("_meta", {}).items()
                        if key != "similar_terms_version"}
        expected_meta = {key: value for key, value in mapping["_meta"].items()
                         if key != "similar_terms_version"}
        if current_meta != expected_meta:
            raise ValueError("Existing index has another schema; use a new ES_INDEX")
        ensure_similarity_fields(client, settings.index)
        # Additive migration: preserve existing documents and analyzers.
        client.indices.put_mapping(index=settings.index, properties={
            "external_ids": mapping["properties"]["external_ids"]})
        ensure_name_search(client, settings)
    else:
        client.indices.create(index=settings.index, mappings=mapping, settings=index_settings())
    count, _ = helpers.bulk(client, (
        {"_index": settings.index, "_id": d["feature_id"], "_source": d} for d in docs
    ), refresh="wait_for")
    return count


def main():
    parser = argparse.ArgumentParser(description="Validate and upsert features; no catalog or index deletion")
    parser.add_argument("--seed", default=str(ROOT / "data" / "features.json"))
    args = parser.parse_args()
    features = json.loads(open(args.seed, encoding="utf-8").read())
    settings = Settings.from_env()
    with connect(settings) as client:
        count = import_seed(client, settings, features)
    print(json.dumps({"index": settings.index, "imported": count, "analyzer": settings.analyzer}))


if __name__ == "__main__":
    main()
