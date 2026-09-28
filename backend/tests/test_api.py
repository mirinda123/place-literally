"""Live ES checks run only with RUN_ES_TESTS=1, in disposable indices."""
import json
import os
import uuid
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.config import ROOT, Settings, connect
from backend.indexing import EMBEDDING_FIELD, EMBEDDING_LANGUAGES, documents, import_seed, index_mapping, index_settings
from backend.main import create_app
from backend.similar import similar_places
from backend.vector_similar import vector_similar_places

FIELDS = {"feature_id", "kind", "names", "location", "literal_name", "literal_meanings", "meaning_id", "external_ids"}

@pytest.fixture(scope="module")
def seed():
    return json.loads((ROOT / "data/features.json").read_text(encoding="utf-8"))

def test_minimal_schema(seed):
    docs = documents(seed)
    assert len(docs) == 11
    assert all(set(d) == FIELDS for d in docs)
    assert all(d["external_ids"]["osm"] for d in docs)
    assert next(d for d in docs if d["feature_id"] == "new-york-us")["meaning_id"] is None
    for extra in ({"analysis_id": "old"}, {"location": {"lon": 200, "lat": 0}}, {"names": {"bad.lang": "x"}}):
        with pytest.raises(ValidationError):
            documents([{**seed[0], **extra}])

@pytest.fixture(scope="module")
def live(seed):
    if os.getenv("RUN_ES_TESTS") != "1":
        pytest.skip("Set RUN_ES_TESTS=1 to test running ES")
    settings = replace(Settings.from_env(), index="literal-name-map-test-" + uuid.uuid4().hex)
    with connect(settings) as client:
        try:
            import_seed(client, settings, seed)
            import_seed(client, settings, seed)
            with TestClient(create_app(settings)) as api:
                yield api, client, settings
        finally:
            assert settings.index.startswith("literal-name-map-test-")
            client.indices.delete(index=settings.index, ignore_unavailable=True)

def search(api, query, **options):
    response = api.get("/api/search", params={"query": query, **options})
    assert response.status_code == 200, response.text
    return response.json()

def ids(response):
    return {d["feature_id"] for d in response["results"]}

def test_only_one_index_and_no_catalog(live):
    api, client, settings = live
    assert api.get("/health").json()["features"] == 11
    assert set(client.indices.get(index=settings.index+"*")) == {settings.index}
    assert api.get("/api/catalog").status_code == 404
    props=client.indices.get_mapping(index=settings.index)[settings.index]["mappings"]["properties"]
    assert set(props) == FIELDS | {"search_names"}
    zh_meaning = props["literal_meanings"]["properties"]["translations"]["properties"]["zh"]
    assert zh_meaning["analyzer"] == "ik_max_word"
    assert zh_meaning["search_analyzer"] == "ik_smart"
    en_meaning = props["literal_meanings"]["properties"]["translations"]["properties"]["en"]
    assert en_meaning["analyzer"] == "english_no_stop"
    meaning_fields = props["literal_meanings"]["properties"]
    assert "embeddings_qwen3_8b_512_v1" not in meaning_fields
    vectors = meaning_fields[EMBEDDING_FIELD]["properties"]
    assert set(vectors) == set(EMBEDDING_LANGUAGES)
    assert all(field["type"] == "dense_vector" and field["dims"] == 512
               and field["similarity"] == "cosine" for field in vectors.values())
    assert props["names"]["properties"]["zh"]["analyzer"] == settings.analyzer
    assert api.get("/api/records").status_code == 404


def test_english_and_japanese_meaning_analysis(live):
    api, client, settings = live
    feature = {"feature_id": "test-ja-analysis", "kind": "city", "names": {"en": "Example"},
               "location": {"lon": 1, "lat": 2}, "literal_name": {"text": "新しい町", "lang": "ja"},
               "literal_meanings": [{"translations": {
                   "en": "not of the old cities", "en-US": "not of the old cities",
                   "ja": "新しい町", "ja-JP": "新しい町"}}]}
    try:
        import_seed(client, settings, [feature])
        props = client.indices.get_mapping(index=settings.index)[settings.index]["mappings"]["properties"]
        translations = props["literal_meanings"]["properties"]["translations"]["properties"]
        assert translations["ja"]["analyzer"] == "kuromoji"
        assert translations["ja-JP"]["analyzer"] == "kuromoji"
        assert translations["en-US"]["analyzer"] == "english_no_stop"
        english = client.indices.analyze(index=settings.index, analyzer="english_no_stop",
                                         text="not of the old cities")
        terms = {token["token"] for token in english["tokens"]}
        assert {"not", "of", "the", "old", "citi"}.issubset(terms)
        japanese = client.indices.analyze(index=settings.index,
                                          field="literal_meanings.translations.ja", text="新しい町")
        assert len(japanese["tokens"]) > 1
        assert "test-ja-analysis" in ids(search(api, "新しい町"))
    finally:
        client.delete(index=settings.index, id=feature["feature_id"], refresh="wait_for")


def test_embedding_vectors_do_not_enter_public_responses(live):
    api, client, settings = live
    feature_id = "test-embedded-feature"
    feature = {"feature_id": feature_id, "kind": "city", "names": {"en": "Vector Test City"},
               "location": {"lon": 1, "lat": 2},
               "literal_name": {"text": "Vector Test City", "lang": "en"},
               "literal_meanings": [{"translations": {"en": "test city"},
                                     EMBEDDING_FIELD: {"en": [1.0] + [0.0] * 511}}]}
    client.index(index=settings.index, id=feature_id, document=feature, refresh="wait_for")
    try:
        for path in (f"/api/features/{feature_id}",
                     "/api/search?query=Vector%20Test%20City",
                     "/api/map-features?limit=1000"):
            response = api.get(path)
            assert response.status_code == 200
            assert EMBEDDING_FIELD not in response.text
        detail = api.get(f"/api/features/{feature_id}").json()
        assert detail["literal_meanings"] == [{"translations": {"en": "test city"}}]
    finally:
        client.delete(index=settings.index, id=feature_id, refresh="wait_for")


def test_vector_similar_exact_multisense_and_all_pages(live):
    api, client, settings = live
    one = [1.0] + [0.0] * 511
    two = [0.0, 1.0] + [0.0] * 510
    three = [0.0, 0.0, 1.0] + [0.0] * 509
    blend = [0.8, 0.6] + [0.0] * 510
    langs = ("zh", "en", "ja", "fr", "es")

    def meaning(label, vector):
        return {"translations": {lang: f"{label} {lang}" for lang in langs},
                EMBEDDING_FIELD: {lang: vector for lang in langs}}

    def feature(feature_id, kind, meanings):
        return {"feature_id": feature_id, "kind": kind, "names": {"en": feature_id},
                "location": {"lon": 1, "lat": 2},
                "literal_name": {"text": feature_id, "lang": "en"},
                "literal_meanings": meanings}

    docs = [feature("vector-origin", "city", [meaning("first", one), meaning("second", two)]),
            feature("vector-country", "country", [meaning("match", one)]),
            feature("vector-state", "state", [meaning("match", blend)]),
            feature("vector-river", "river", [meaning("other", three), meaning("match", two)]),
            feature("vector-weak", "city", [meaning("other", three)]),
            feature("vector-empty", "city", [{"translations": {"en": "without vectors"}}]),
            feature("vector-partial", "city", [{"translations": {"zh": "仅英文向量", "en": "English only"},
                                                  EMBEDDING_FIELD: {"en": three}}])]
    for doc in docs:
        client.index(index=settings.index, id=doc["feature_id"], document=doc)
    client.indices.refresh(index=settings.index)
    service = api.app.state.query_embeddings
    original_embed = service.embed
    service.embed = lambda texts: {text: one if text.startswith("first") else two for text in texts}
    try:
        for lang in langs:
            response = api.get("/api/features/vector-origin/vector-similar",
                               params={"lang": lang, "min_similarity": 0.6})
            assert response.status_code == 200, response.text
            payload = response.json()
            results = {item["feature"]["feature_id"]: item for item in payload["results"]}
            assert payload["available"] and payload["total"] == 3
            assert set(results) == {"vector-country", "vector-state", "vector-river"}
            assert results["vector-country"]["source_meaning_index"] == 0
            assert results["vector-river"]["source_meaning_index"] == 1
            assert results["vector-river"]["matched_meaning_index"] == 1
            assert abs(results["vector-state"]["score"] - 0.8) < 0.002
            assert EMBEDDING_FIELD not in response.text
        origin = client.get(index=settings.index, id="vector-origin",
                            source_exclude_vectors=False)["_source"]
        paged = vector_similar_places(client, settings.index, origin, "zh", 0.6,
                                      service.embed, page_size=2)
        assert paged["total"] == 3
        service.embed = lambda _texts: (_ for _ in ()).throw(RuntimeError("provider unavailable"))
        assert api.get("/api/features/vector-empty/vector-similar").json()["available"] is False
        assert api.get("/api/features/vector-partial/vector-similar",
                       params={"lang": "zh"}).json()["available"] is False
        assert api.get("/api/features/vector-origin/vector-similar").status_code == 503
        assert api.get("/api/features/vector-missing/vector-similar").status_code == 404
        assert api.get("/api/features/vector-origin/vector-similar",
                       params={"lang": "ko"}).status_code == 422
        assert api.get("/api/features/vector-origin/vector-similar",
                       params={"min_similarity": 1.1}).status_code == 422
    finally:
        service.embed = original_embed
        for doc in docs:
            client.delete(index=settings.index, id=doc["feature_id"], refresh="wait_for")

@pytest.mark.parametrize("query,first", [("南京","nanjing-cn"),("Nanjing","nanjing-cn"),("Kyōto","kyoto-jp"),("Napoli","naples-it")])
def test_names(live, query, first):
    result=search(live[0],query)
    assert result["results"][0]["feature_id"] == first
    assert result["results"][0]["match_kind"] == "name"


def test_chinese_city_name_without_administrative_suffix_ranks_first(live):
    api, client, settings = live
    city = {"feature_id": "test-zhengzhou", "kind": "city", "names": {"zh": "郑州市"},
            "location": {"lon": 113.6, "lat": 34.7}}
    airport = {"feature_id": "test-zhengzhou-airport", "kind": "city",
               "names": {"zh": "郑州航空港区"}, "location": {"lon": 113.8, "lat": 34.6}}
    try:
        import_seed(client, settings, [city, airport])
        result = search(api, "郑州")
        assert result["results"][0]["feature_id"] == city["feature_id"]
        assert result["results"][0]["match_kind"] == "name"
    finally:
        for feature in (city, airport):
            client.delete(index=settings.index, id=feature["feature_id"], refresh="wait_for")

@pytest.mark.parametrize("query", ["新城","new city","新的定居点"])
def test_new_city_excludes_new_york(live,query):
    assert ids(search(live[0],query)) == {"naples-it","veliky-novgorod-ru"}

def test_scopes_and_modifiers(live):
    api=live[0]
    assert ids(search(api,"南方的都城")) == {"nanjing-cn"}
    assert ids(search(api,"首都",scope="exact")) == {"seoul-kr","kyoto-jp"}
    assert search(api,"首都")["total"] == 5
    assert ids(search(api,"中心")) == {"china-cn"}
    assert search(api,"中心",scope="theme")["total"] == 6
    assert search(api,"新城",scope="exact")["total"] == 2
    assert "new-york-us" in ids(search(api,"名字里有新",scope="theme"))
    assert search(api,"水")["total"] == 0
    assert "否定" in search(api,"不要首都")["notice"]

def test_filters_pagination_details(live):
    api=live[0]
    a,b=search(api,"新城",limit=1),search(api,"新城",limit=1,offset=1)
    assert a["total"]==2 and ids(a).isdisjoint(ids(b))
    assert search(api,"首都",meaning_id="southern-capital")["total"]==1
    assert search(api,"首都",kind="river")["total"]==0
    assert api.post("/api/search",json={"query":"新城"}).json()["total"]==2
    for params in ({"query":" "},{"query":"x","limit":101}):
        assert api.get("/api/search",params=params).status_code==422
    detail=api.get("/api/features/nanjing-cn").json()
    assert set(detail)==FIELDS
    assert detail["literal_meanings"][0]["translations"]["zh"]=="南方的都城"
    assert api.get("/api/features/missing").status_code==404
    assert ids(api.get("/api/features/naples-it/related").json())=={"veliky-novgorod-ru"}
    assert api.get("/api/features/new-york-us/related").json()["results"]==[]
    assert api.get("/api/features",params={"meaning_id":"new-city"}).json()["total"]==2

def test_new_language_and_unknown_meanings(live):
    api,client,settings=live
    feature={"feature_id":"test-river","kind":"river","names":{"fr":"Rivière exemple"},
             "location":{"lon":1,"lat":2},"literal_name":None,"literal_meanings":[],"meaning_id":None}
    try:
        import_seed(client,settings,[feature])
        assert ids(search(api,"Rivière exemple"))=={"test-river"}
        assert api.get("/api/features/test-river/related").json()["results"]==[]
        feature.update(literal_name={"text":"Exemple","lang":"fr"},literal_meanings=[{"translations":{"fr":"rivière paisible"}}])
        import_seed(client,settings,[feature])
        assert ids(search(api,"paisible"))=={"test-river"}
    finally:
        client.delete(index=settings.index,id=feature["feature_id"],refresh="wait_for")


def test_meaning_search_keeps_distinct_interpretations_separate(live):
    api, client, settings = live
    feature = {"feature_id": "two-senses", "kind": "country", "names": {"en": "Testland"},
               "location": {"lon": 1, "lat": 2}, "literal_name": {"text": "Testland", "lang": "en"},
               "literal_meanings": [{"translations": {"en": "brave land"}},
                                    {"translations": {"en": "spear bearers"}}], "meaning_id": None}
    try:
        import_seed(client, settings, [feature])
        assert "two-senses" in ids(search(api, "brave"))
        assert "two-senses" in ids(search(api, "spear"))
        assert "two-senses" not in ids(search(api, "brave bearers"))
    finally:
        client.delete(index=settings.index, id=feature["feature_id"], refresh="wait_for")


def test_similar_places_across_kinds_and_languages(live):
    api, client, settings = live
    translations = {"zh": "紫色的桥和蓝色的月亮", "en": "violet bridge beneath a copper moon",
                    "es": "puente violeta bajo una luna de cobre",
                    "fr": "pont violet sous une lune de cuivre", "ja": "紫の橋と青い月"}
    origin = {"feature_id": "similar-origin", "kind": "city", "names": {"en": "Origin"},
              "location": {"lon": 0, "lat": 0}, "literal_name": {"text": "Origin", "lang": "en"},
              "literal_meanings": [{"translations": {"en": "copper harbor"}},
                                   {"translations": translations}], "meaning_id": None}
    match = {**origin, "feature_id": "similar-match", "location": {"lon": 1, "lat": 0},
             "literal_meanings": [{"translations": translations}]}
    country = {**match, "feature_id": "similar-country", "kind": "country"}
    state = {**match, "feature_id": "similar-state", "kind": "state"}
    river = {**match, "feature_id": "similar-river", "kind": "river"}
    empty = {**origin, "feature_id": "similar-empty", "literal_name": None,
             "literal_meanings": []}
    only_english = {**match, "feature_id": "similar-only-en", "kind": "town",
                    "literal_meanings": [{"translations": {"en": translations["en"]}}]}
    two_languages = {**match, "feature_id": "similar-two-langs", "kind": "lake",
                     "literal_meanings": [{"translations": {
                         "zh": translations["zh"], "en": translations["en"]}}]}
    lonely = {**match, "feature_id": "similar-lonely",
              "literal_meanings": [{"translations": {"en": "unparalleled zephyr labyrinth"}}]}
    background = [{**match, "feature_id": f"similar-background-{i}",
                   "literal_meanings": [{"translations": {key: "ordinary settlement" for key in translations}}]}
                  for i in range(25)]
    try:
        import_seed(client, settings, [origin, match, country, state, river,
                                       empty, only_english, two_languages, lonely, *background])
        for language in translations:
            response = api.get("/api/features/similar-origin/similar", params={"lang": language})
            assert response.status_code == 200, response.text
            payload = response.json()
            results = {item["feature"]["feature_id"]: item for item in payload["results"]}
            assert {"similar-match", "similar-country", "similar-state", "similar-river",
                    "similar-two-langs"} <= results.keys(), (language, payload)
            assert "similar-origin" not in results
            assert "similar-only-en" not in results
            for feature_id in ("similar-match", "similar-country", "similar-state", "similar-river"):
                assert results[feature_id]["source_meaning_index"] == 1
                assert results[feature_id]["matched_meaning_index"] == 0
                assert results[feature_id]["score"] > 0
            assert payload["threshold"] is None
            assert "similar-lonely" not in results
            assert not any(feature_id.startswith("similar-background-") for feature_id in results)
        for feature_id, expected in (("similar-country", "similar-origin"),
                                     ("similar-state", "similar-country"),
                                     ("similar-river", "similar-country")):
            results = {item["feature"]["feature_id"] for item in api.get(
                f"/api/features/{feature_id}/similar", params={"lang": "en"}).json()["results"]}
            assert expected in results
            assert feature_id not in results
        assert api.get("/api/features/similar-empty/similar", params={"lang": "fr"}).json()["results"] == []
        no_translation = api.get("/api/features/similar-only-en/similar", params={"lang": "fr"}).json()
        assert no_translation["results"] == [] and no_translation["threshold"] is None
        other_languages = api.get("/api/features/similar-two-langs/similar", params={"lang": "fr"}).json()
        assert other_languages["total"] > 0
        assert api.get("/api/features/similar-lonely/similar", params={"lang": "en"}).json()["results"] == []
        assert api.get("/api/features/similar-origin/similar", params={"lang": "ko"}).status_code == 422
    finally:
        for feature in (origin, match, country, state, river, empty, only_english, two_languages, lonely, *background):
            client.delete(index=settings.index, id=feature["feature_id"], refresh="wait_for")


def test_similar_requires_two_languages_in_one_interpretation(live):
    _, client, settings = live
    isolated = replace(settings, index="literal-name-map-test-match-" + uuid.uuid4().hex)
    origin_text = {"zh": "中央之国", "en": "central country", "ja": "中央の国",
                   "fr": "pays du centre", "es": "país del centro"}
    central_text = {"zh": "中央之岛", "en": "central island", "ja": "中央の島",
                    "fr": "île du centre", "es": "isla del centro"}
    generic_text = {"zh": "大韩人民之国", "en": "country of the Korean people",
                    "ja": "韓民族の国", "fr": "pays du peuple coréen",
                    "es": "país del pueblo coreano"}
    base = {"kind": "city", "names": {"en": "Test place"},
            "location": {"lon": 0, "lat": 0},
            "literal_name": {"text": "Test place", "lang": "en"}, "meaning_id": None}
    docs = [
        {**base, "feature_id": "match-origin", "literal_meanings": [{"translations": origin_text}]},
        {**base, "feature_id": "match-equal", "kind": "river",
         "literal_meanings": [{"translations": origin_text}]},
        {**base, "feature_id": "match-central", "kind": "island",
         "literal_meanings": [{"translations": central_text}]},
        {**base, "feature_id": "match-two-languages", "kind": "town",
         "literal_meanings": [{"translations": {
             "zh": central_text["zh"], "en": central_text["en"]}}]},
        {**base, "feature_id": "match-generic", "kind": "country",
         "literal_meanings": [{"translations": generic_text}]},
        {**base, "feature_id": "match-split-senses",
         "literal_meanings": [{"translations": {"zh": origin_text["zh"]}},
                              {"translations": {"en": origin_text["en"]}}]},
        {**base, "feature_id": "match-only-stop-word",
         "literal_meanings": [{"translations": {"zh": "的"}}]},
        *[{**base, "feature_id": f"match-background-{i}",
           "literal_meanings": [{"translations": {lang: "ordinary settlement"
                                                   for lang in origin_text}}]}
          for i in range(40)],
    ]
    try:
        import_seed(client, isolated, docs)
        with TestClient(create_app(isolated)) as api:
            for lang in origin_text:
                response = api.get("/api/features/match-origin/similar", params={"lang": lang})
                assert response.status_code == 200, response.text
                ids = {hit["feature"]["feature_id"] for hit in response.json()["results"]}
                assert ids == {"match-equal", "match-central", "match-two-languages"}, (lang, response.json())
                assert response.json()["threshold"] is None
                scores = {hit["feature"]["feature_id"]: hit["score"]
                          for hit in response.json()["results"]}
                assert scores["match-equal"] == 5
                assert scores["match-two-languages"] == 2

            split_source = api.get("/api/features/match-split-senses/similar", params={"lang": "zh"})
            assert split_source.status_code == 200 and split_source.json()["results"] == []

            all_stop = api.get("/api/features/match-only-stop-word/similar", params={"lang": "zh"})
            assert all_stop.status_code == 200, all_stop.text
            assert all_stop.json()["results"] == []
            assert all_stop.json()["threshold"] is None
    finally:
        client.indices.delete(index=isolated.index, ignore_unavailable=True)


def test_similar_ignores_generic_city_words(live):
    _, client, settings = live
    base = {"kind": "city", "names": {"en": "Test place"},
            "location": {"lon": 0, "lat": 0},
            "literal_name": {"text": "Test place", "lang": "en"}, "meaning_id": None}
    taipei = {**base, "feature_id": "test-taipei-city-words",
              "literal_meanings": [{"translations": {
                  "zh": "台湾北部的城市", "en": "City of northern Taiwan",
                  "ja": "台湾北部の都市", "fr": "Ville du nord de Taïwan",
                  "es": "Ciudad del norte de Taiwán"}}]}
    minneapolis = {**base, "feature_id": "test-minneapolis-city-words",
                   "literal_meanings": [{"translations": {
                       "zh": "水之城", "en": "City of water", "ja": "水の街",
                       "fr": "Ville de l’eau", "es": "Ciudad del agua"}}]}
    northern_taiwan = {**base, "feature_id": "test-northern-taiwan-city-words",
                       "literal_meanings": [{"translations": {
                           "zh": "台湾北部", "en": "Northern Taiwan",
                           "ja": "台湾北部", "fr": "Nord de Taïwan",
                           "es": "Norte de Taiwán"}}]}
    docs = [taipei, minneapolis, northern_taiwan]
    try:
        import_seed(client, settings, docs)
        taipei_matches = {item["feature"]["feature_id"] for item in similar_places(
            client, settings.index, taipei, "zh")["results"]}
        assert minneapolis["feature_id"] not in taipei_matches
        assert northern_taiwan["feature_id"] in taipei_matches
        reverse_matches = {item["feature"]["feature_id"] for item in similar_places(
            client, settings.index, minneapolis, "en")["results"]}
        assert taipei["feature_id"] not in reverse_matches
    finally:
        for feature in docs:
            client.delete(index=settings.index, id=feature["feature_id"], refresh="wait_for")


def test_similar_ignores_generic_land_words(live):
    _, client, settings = live
    base = {"kind": "city", "names": {"en": "Test place"},
            "location": {"lon": 0, "lat": 0},
            "literal_name": {"text": "Test place", "lang": "en"}, "meaning_id": None}
    nagoya = {**base, "feature_id": "test-nagoya-land-words",
              "literal_meanings": [{"translations": {
                  "zh": "气候温和之地", "en": "Land of a mild climate",
                  "ja": "気候が穏やかな土地", "fr": "Terre au climat doux",
                  "es": "Tierra de clima templado"}}]}
    oakland = {**base, "feature_id": "test-oakland-land-words",
               "literal_meanings": [{"translations": {
                   "zh": "橡树之地", "en": "Land of oaks", "ja": "オークの木が生える土地",
                   "fr": "Terre des chênes", "es": "Tierra de robles"}}]}
    mild_climate = {**base, "feature_id": "test-mild-climate-land-words",
                    "literal_meanings": [{"translations": {
                        "zh": "气候温和", "en": "Mild climate", "ja": "穏やかな気候",
                        "fr": "Climat doux", "es": "Clima templado"}}]}
    docs = [nagoya, oakland, mild_climate]
    try:
        import_seed(client, settings, docs)
        matches = {item["feature"]["feature_id"] for item in similar_places(
            client, settings.index, nagoya, "zh")["results"]}
        assert oakland["feature_id"] not in matches
        assert mild_climate["feature_id"] in matches
    finally:
        for feature in docs:
            client.delete(index=settings.index, id=feature["feature_id"], refresh="wait_for")


def test_similar_ignores_generic_place_words(live):
    _, client, settings = live
    base = {"kind": "city", "names": {"en": "Test place"},
            "location": {"lon": 0, "lat": 0},
            "literal_name": {"text": "Test place", "lang": "en"}, "meaning_id": None}
    new_mexico = {**base, "feature_id": "test-new-mexico-place-words",
                  "literal_meanings": [{"translations": {
                      "zh": "梅希特利的新地方", "en": "New place of Mexitli",
                      "ja": "メシトリの新しい場所", "fr": "Nouveau lieu de Mexitli",
                      "es": "Nuevo lugar de Mexitli"}}]}
    prague = {**base, "feature_id": "test-prague-place-words",
              "literal_meanings": [{"translations": {
                  "zh": "被阳光晒干的地方", "en": "Sun-parched place",
                  "ja": "日干しの場所", "fr": "Lieu desséché par le soleil",
                  "es": "Lugar secado por el sol"}}]}
    new_water = {**base, "feature_id": "test-new-water-place-words",
                 "literal_meanings": [{"translations": {
                     "zh": "新水域", "en": "New water", "ja": "新しい水域",
                     "fr": "Nouvelle eau", "es": "Agua nueva"}}]}
    new_mexitli = {**base, "feature_id": "test-new-mexitli-place-words",
                   "literal_meanings": [{"translations": {
                       "zh": "梅希特利的新城区", "en": "New district of Mexitli",
                       "ja": "メシトリの新しい地区", "fr": "Nouveau quartier de Mexitli",
                       "es": "Nuevo barrio de Mexitli"}}]}
    docs = [new_mexico, prague, new_water, new_mexitli]
    try:
        import_seed(client, settings, docs)
        matches = {item["feature"]["feature_id"] for item in similar_places(
            client, settings.index, new_mexico, "zh")["results"]}
        assert prague["feature_id"] not in matches
        assert new_water["feature_id"] not in matches
        assert new_mexitli["feature_id"] in matches
    finally:
        for feature in docs:
            client.delete(index=settings.index, id=feature["feature_id"], refresh="wait_for")


def test_similar_needs_two_terms_per_multiterm_language(live):
    _, client, settings = live
    base = {"kind": "city", "names": {"en": "Test place"},
            "location": {"lon": 0, "lat": 0},
            "literal_name": {"text": "Test place", "lang": "en"}, "meaning_id": None}
    origin = {**base, "feature_id": "test-two-terms-origin",
              "literal_meanings": [{"translations": {
                  "en": "blue harbor", "fr": "port bleu"}}]}
    one_term = {**base, "feature_id": "test-two-terms-weak",
                "literal_meanings": [{"translations": {
                    "en": "blue meadow", "fr": "ciel bleu"}}]}
    two_terms = {**base, "feature_id": "test-two-terms-strong",
                 "literal_meanings": [{"translations": {
                     "en": "blue harbor district", "fr": "quartier du port bleu"}}]}
    docs = [origin, one_term, two_terms]
    try:
        import_seed(client, settings, docs)
        matches = {item["feature"]["feature_id"] for item in similar_places(
            client, settings.index, origin, "en")["results"]}
        assert one_term["feature_id"] not in matches
        assert two_terms["feature_id"] in matches
    finally:
        for feature in docs:
            client.delete(index=settings.index, id=feature["feature_id"], refresh="wait_for")


def test_similar_riverside_words_do_not_link_manchester_to_london(live):
    _, client, settings = live
    base = {"kind": "city", "names": {"en": "Test place"},
            "location": {"lon": 0, "lat": 0},
            "literal_name": {"text": "Test place", "lang": "en"}, "meaning_id": None}
    manchester = {**base, "feature_id": "test-riverside-manchester",
                  "literal_meanings": [{"translations": {
                      "zh": "名为母亲的河流旁的罗马堡垒",
                      "en": "Roman fort beside the river called Mother",
                      "ja": "母と呼ばれる川のほとりのローマの砦",
                      "fr": "Fort romain au bord de la rivière appelée Mère",
                      "es": "Fuerte romano junto al río llamado Madre"}}]}
    london = {**base, "feature_id": "test-riverside-london",
              "literal_meanings": [{"translations": {
                  "zh": "宽阔奔流的河畔聚落",
                  "en": "Settlement by the wide-flowing river",
                  "ja": "広く流れる川のほとりの集落",
                  "fr": "Établissement au bord du large fleuve qui coule",
                  "es": "Asentamiento junto al río ancho y caudaloso"}}]}
    minsk = {**base, "feature_id": "test-riverside-minsk",
             "literal_meanings": [{"translations": {
                 "zh": "小河边的聚落", "en": "Settlement by the small river",
                 "ja": "小さな川のほとりの集落",
                 "fr": "Village au bord de la petite rivière",
                 "es": "Poblado junto al río pequeño"}}]}
    same_meaning = {**base, "feature_id": "test-riverside-mother-fort",
                    "literal_meanings": manchester["literal_meanings"]}
    docs = [manchester, london, minsk, same_meaning]
    try:
        import_seed(client, settings, docs)
        results = {item["feature"]["feature_id"] for item in similar_places(
            client, settings.index, manchester, "zh")["results"]}
        assert london["feature_id"] not in results
        assert minsk["feature_id"] not in results
        assert same_meaning["feature_id"] in results
        for language, word in (("zh", "河流"), ("en", "river"), ("ja", "川"),
                               ("fr", "rivière"), ("es", "río")):
            tokens = {item["token"] for item in client.indices.analyze(
                index=settings.index, analyzer=f"similar_{language}_v3",
                text=manchester["literal_meanings"][0]["translations"][language])["tokens"]}
            assert word in tokens, (language, tokens)
    finally:
        for feature in docs:
            client.delete(index=settings.index, id=feature["feature_id"], refresh="wait_for")


def test_similar_places_page_every_kind_in_one_pit(live):
    _, client, settings = live
    phrase = "violet bridge beneath copper moon"
    base = {"kind": "city", "names": {"en": "Test place"},
            "location": {"lon": 0, "lat": 0}, "literal_name": {"text": "Test place", "lang": "en"},
            "literal_meanings": [{"translations": {"en": phrase,
                                                   "zh": "紫色的桥下有铜色的月亮"}}], "meaning_id": None}
    docs = [{**base, "feature_id": "similar-page-origin"}]
    kinds = ("city", "country", "state", "town", "river", "lake", "sea", "province", "metropolis")
    docs.extend({**base, "feature_id": f"similar-page-{i:02d}", "kind": kind}
                for i, kind in enumerate(kinds))
    late = {**base, "feature_id": "similar-page-late"}

    class UpdatingClient:
        def __init__(self):
            self.searches = 0

        def __getattr__(self, name):
            return getattr(client, name)

        def search(self, **kwargs):
            self.searches += 1
            if self.searches == 3:
                import_seed(client, settings, [late])
            return client.search(**kwargs)

    try:
        import_seed(client, settings, docs)
        wrapper = UpdatingClient()
        result = similar_places(wrapper, settings.index, docs[0], "en", page_size=2)
        found = [item["feature"]["feature_id"] for item in result["results"]]
        assert result["total"] == 9
        assert set(found) == {f"similar-page-{i:02d}" for i in range(9)}
        assert len(found) == len(set(found))
        assert wrapper.searches >= 5
    finally:
        for feature in [*docs, late]:
            client.options(ignore_status=404).delete(
                index=settings.index, id=feature["feature_id"], refresh="wait_for")

def test_missing_index_is_service_error(live):
    settings=replace(live[2],index="literal-name-map-test-missing-"+uuid.uuid4().hex)
    with TestClient(create_app(settings)) as api:
        assert api.get("/api/search",params={"query":"新城"}).status_code==503
        assert api.get("/api/features/unknown").status_code==503
        assert api.get("/api/features/resolve",params={"osm":"node/244081381"}).status_code==503


def test_osm_identity_validation(seed):
    for osm in (["244081381"], ["node/0"], ["node/-1"], ["node/12", "node/12"], ["NODE/12"], ["node/*"]):
        with pytest.raises(ValidationError):
            documents([{**seed[0], "external_ids": {"osm": osm}}])


def test_map_resolver_exact_identity_and_ambiguity(live, seed):
    api, client, settings = live
    def resolve(osm):
        response=api.get("/api/features/resolve",params={"osm":osm})
        assert response.status_code==200,response.text
        return response.json()
    assert resolve("node/244081381")["feature"]["feature_id"]=="nanjing-cn"
    assert resolve("node/424313582")["feature"]["feature_id"]=="china-cn"
    assert resolve("way/244081381")["status"]=="not_found"
    assert resolve("node/999999999999")["feature"] is None
    for invalid in ("244081381", "node/0", "node/*"):
        assert api.get("/api/features/resolve",params={"osm":invalid}).status_code==422
    # A second external object may map to the same entity; duplicate ownership
    # by different entities must be reported instead of choosing a random hit.
    duplicate={**seed[0],"feature_id":"test-osm-duplicate","external_ids":{"osm":["node/244081381","relation/999999999999"]}}
    try:
        import_seed(client,settings,[duplicate])
        result=resolve("node/244081381")
        assert result["status"]=="ambiguous" and result["feature"] is None
        assert resolve("relation/999999999999")["feature"]["feature_id"]==duplicate["feature_id"]
    finally:
        client.delete(index=settings.index,id=duplicate["feature_id"],refresh="wait_for")


def test_additive_mapping_migration(seed):
    if os.getenv("RUN_ES_TESTS")!="1":
        pytest.skip("Set RUN_ES_TESTS=1")
    settings=replace(Settings.from_env(),index="literal-name-map-test-"+uuid.uuid4().hex)
    with connect(settings) as client:
        try:
            mapping=index_mapping(settings.analyzer)
            del mapping["properties"]["external_ids"]
            del mapping["properties"]["search_names"]
            for template in mapping["dynamic_templates"]:
                next(iter(template.values()))["mapping"].pop("copy_to", None)
            client.indices.create(index=settings.index,mappings=mapping,settings=index_settings())
            old={k:v for k,v in seed[0].items() if k!="external_ids"}
            client.index(index=settings.index,id="legacy-preserved",document={**old,"feature_id":"legacy-preserved"},refresh=True)
            import_seed(client,settings,seed)
            assert client.get(index=settings.index,id="legacy-preserved")["_source"]["feature_id"]=="legacy-preserved"
            assert client.count(index=settings.index)["count"]==12
            assert client.count(index=settings.index,query={"exists":{"field":"search_names"}})["count"]==12
        finally:
            client.indices.delete(index=settings.index,ignore_unavailable=True)
