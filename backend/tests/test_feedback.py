"""Feedback writes are isolated from place data and checked against the selected meaning."""

from copy import deepcopy
from dataclasses import replace
import json
import os
from uuid import uuid4

from elastic_transport import TransportError
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.config import ROOT, Settings, connect
from backend.indexing import import_seed
from backend.main import create_app


class FakeIndices:
    def __init__(self):
        self.created = {}

    def exists(self, *, index):
        return index in self.created

    def create(self, *, index, mappings):
        self.created[index] = mappings


class FakeElasticsearch:
    def __init__(self):
        self.indices = FakeIndices()
        self.features = {
            "empty": {"feature_id": "empty", "names": {"en": "Empty"},
                      "literal_name": None, "literal_meanings": []},
            "single": {"feature_id": "single", "names": {"en": "Single"},
                       "literal_name": {"text": "Single", "lang": "en"},
                       "literal_meanings": [{"translations": {"en": "one meaning", "zh": "一个含义"}}]},
            "multiple": {"feature_id": "multiple", "names": {"en": "Multiple"},
                         "literal_name": {"text": "Multiple", "lang": "en"},
                         "literal_meanings": [{"translations": {"en": "first"}},
                                              {"translations": {"en": "second"}}]},
        }
        self.feedback = {}
        self.fail_write = False

    def get(self, *, index, id, **kwargs):
        if id not in self.features:
            raise HTTPException(404, "Place not found")
        return {"_source": deepcopy(self.features[id])}

    def index(self, *, index, id, document, refresh):
        if self.fail_write:
            raise TransportError("offline")
        self.feedback[id] = deepcopy(document)

    def close(self):
        pass


def client_for(monkeypatch):
    fake = FakeElasticsearch()
    monkeypatch.setattr("backend.main.connect", lambda settings: fake)
    settings = Settings(index="features-feedback-test", feedback_index="place-feedback-test")
    return fake, TestClient(create_app(settings))


def payload(feature_id, meaning_index):
    return {"feature_id": feature_id, "meaning_index": meaning_index,
            "language": "en", "description": "The current meaning is wrong."}


def test_empty_place_feedback_does_not_change_the_feature(monkeypatch):
    fake, api = client_for(monkeypatch)
    before = deepcopy(fake.features["empty"])
    with api:
        response = api.post("/api/feedback", json=payload("empty", None))
    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    assert fake.feedback[response.json()["id"]]["meaning_snapshot"] is None
    assert fake.features["empty"] == before
    assert set(fake.indices.created) == {"place-feedback-test"}


def test_single_and_multiple_meanings_keep_the_selected_snapshot(monkeypatch):
    fake, api = client_for(monkeypatch)
    with api:
        single = api.post("/api/feedback", json=payload("single", 0))
        multiple = api.post("/api/feedback", json={**payload("multiple", 1),
            "suggested_meaning": "better meaning", "source_url": "https://example.com/source"})
        assert api.post("/api/feedback", json=payload("single", None)).status_code == 422
        assert api.post("/api/feedback", json=payload("multiple", 2)).status_code == 422
        assert api.post("/api/feedback", json=payload("empty", 0)).status_code == 422
    assert single.status_code == multiple.status_code == 201
    saved = fake.feedback[multiple.json()["id"]]
    assert saved["meaning_index"] == 1
    assert saved["meaning_snapshot"] == {"translations": {"en": "second"}}
    assert saved["original_name"] == {"text": "Multiple", "lang": "en"}
    assert saved["suggested_meaning"] == "better meaning"
    assert fake.features["multiple"]["literal_meanings"][1]["translations"]["en"] == "second"


def test_invalid_input_missing_place_and_service_failure(monkeypatch):
    fake, api = client_for(monkeypatch)
    with api:
        assert api.post("/api/feedback", json=payload("missing", None)).status_code == 404
        assert api.post("/api/feedback", json={**payload("single", 0), "description": "  "}).status_code == 422
        assert api.post("/api/feedback", json={**payload("single", 0), "source_url": "not a URL"}).status_code == 422
        fake.fail_write = True
        assert api.post("/api/feedback", json=payload("single", 0)).status_code == 503
    assert not fake.feedback


def test_short_description_is_allowed_for_local_feedback(monkeypatch):
    fake, api = client_for(monkeypatch)
    with api:
        response = api.post("/api/feedback", json={**payload("single", 0), "description": "test"})
    assert response.status_code == 201
    assert fake.feedback[response.json()["id"]]["description"] == "test"


def test_feedback_round_trip_in_elasticsearch():
    if os.getenv("RUN_ES_TESTS") != "1":
        import pytest
        pytest.skip("Set RUN_ES_TESTS=1 to test running Elasticsearch")
    suffix = uuid4().hex
    settings = replace(Settings.from_env(), index="features-feedback-test-" + suffix,
                       feedback_index="place-feedback-test-" + suffix)
    seed = json.loads((ROOT / "data/features.json").read_text(encoding="utf-8"))
    with connect(settings) as client:
        try:
            import_seed(client, settings, seed)
            feature = next(item for item in seed if item.get("literal_meanings"))
            feature_id = feature["feature_id"]
            before = client.get(index=settings.index, id=feature_id)["_source"]
            with TestClient(create_app(settings)) as api:
                response = api.post("/api/feedback", json=payload(feature_id, 0))
            assert response.status_code == 201, response.text
            saved = client.get(index=settings.feedback_index, id=response.json()["id"])["_source"]
            assert saved["feature_id"] == feature_id
            assert saved["meaning_snapshot"]["translations"] == feature["literal_meanings"][0]["translations"]
            assert client.get(index=settings.index, id=feature_id)["_source"] == before
        finally:
            client.indices.delete(index=settings.feedback_index, ignore_unavailable=True)
            client.indices.delete(index=settings.index, ignore_unavailable=True)
