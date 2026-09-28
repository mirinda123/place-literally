import json
import time
from contextlib import nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace

from backend.embed_meanings import (DEFAULT_INSTRUCT, DIMENSIONS, EmbeddingClient,
                                    apply_vectors, create_run_logger, load_features,
                                    pending_texts, read_plan, run_job)
from backend.indexing import EMBEDDING_FIELD, EMBEDDING_LANGUAGES, LiteralMeaning


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_native_embedding_uses_instruct_only_for_query(tmp_path, monkeypatch):
    calls = []
    vector = [1.0] + [0.0] * (DIMENSIONS - 1)

    def fake_urlopen(request, timeout):
        body = json.loads(request.data)
        calls.append(body)
        assert timeout == 90
        return FakeResponse({"output": {"embeddings": [
            {"text_index": index, "embedding": vector}
            for index, _ in enumerate(body["input"]["texts"])]},
            "usage": {"total_tokens": 5}})

    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setattr("backend.embed_meanings.urlopen", fake_urlopen)
    client = EmbeddingClient(tmp_path, "https://dashscope.aliyuncs.com/api/v1/embed",
                             DEFAULT_INSTRUCT, batch_size=20)
    assert client.embed(["central country"], "document")["central country"] == vector
    assert client.embed(["central country"], "query")["central country"] == vector
    assert calls[0]["parameters"] == {"dimension": 512, "output_type": "dense",
                                       "text_type": "document"}
    assert calls[1]["parameters"]["instruct"] == DEFAULT_INSTRUCT
    assert calls[1]["parameters"]["text_type"] == "query"
    assert client.calls == 2 and client.tokens == 10
    assert [batch["text_type"] for batch in client.api_batches] == ["document", "query"]
    assert all(batch["texts"] == 1 and batch["elapsed_seconds"] >= 0
               for batch in client.api_batches)
    assert client.api_seconds >= 0
    assert client.embed(["central country"], "document")["central country"] == vector
    assert client.calls == 2 and client.cache_hits == 1


def test_pilot_plan_has_ten_of_each():
    from backend.config import ROOT
    entries = read_plan(ROOT / "data" / "embedding-pilot-20.json")
    assert len(entries) == 20
    assert [kind for _, kind in entries].count("country") == 10
    assert [kind for _, kind in entries].count("city") == 10


def test_plan_accepts_an_additional_thirty_without_duplicates(tmp_path):
    plan = {"countries": [f"country-{i}" for i in range(15)],
            "cities": [f"city-{i}" for i in range(15)]}
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    assert len(read_plan(path)) == 30
    plan["cities"].append("country-0")
    path.write_text(json.dumps(plan), encoding="utf-8")
    import pytest
    with pytest.raises(ValueError, match="distinct"):
        read_plan(path)


def test_validated_meaning_preserves_only_populated_vectors():
    vector = [1.0] + [0.0] * (DIMENSIONS - 1)
    empty = LiteralMeaning(translations={"en": "test city"})
    assert EMBEDDING_FIELD not in empty.model_dump()
    with_vector = LiteralMeaning.model_validate({"translations": {"en": "test city"},
                                                EMBEDDING_FIELD: {"en": vector}})
    assert with_vector.model_dump()[EMBEDDING_FIELD]["en"] == vector


def test_apply_vectors_preserves_translations_and_other_fields():
    vector = [1.0] + [0.0] * (DIMENSIONS - 1)
    meaning = {"translations": {lang: "central country" for lang in EMBEDDING_LANGUAGES}}
    doc = {"feature_id": "example", "literal_meanings": [meaning]}

    class FakeIndices:
        refreshed = False

        def refresh(self, *, index):
            assert index == "features-v9"
            self.refreshed = True

    class FakeES:
        indices = FakeIndices()
        patch = None

        def get(self, *, index, id, source_exclude_vectors):
            assert index == "features-v9" and id == "example"
            assert source_exclude_vectors is False
            return {"_source": doc, "_seq_no": 3, "_primary_term": 1}

        def update(self, *, index, id, doc, if_seq_no, if_primary_term):
            assert (index, id, if_seq_no, if_primary_term) == ("features-v9", "example", 3, 1)
            self.patch = doc

    client = FakeES()
    assert apply_vectors(client, "features-v9", [doc], {"central country": vector}) == 1
    saved = client.patch["literal_meanings"][0]
    assert saved["translations"] == meaning["translations"]
    assert set(saved[EMBEDDING_FIELD]) == set(EMBEDDING_LANGUAGES)
    assert client.indices.refreshed
    assert EMBEDDING_FIELD not in doc["literal_meanings"][0]


def test_existing_vectors_are_loaded_and_not_rewritten():
    vector = [1.0] + [0.0] * (DIMENSIONS - 1)
    doc = {"feature_id": "example", "kind": "country", "literal_meanings": [
        {"translations": {lang: "central country" for lang in EMBEDDING_LANGUAGES},
         EMBEDDING_FIELD: {lang: vector for lang in EMBEDDING_LANGUAGES}}]}

    class FakeES:
        def get(self, *, index, id, source_exclude_vectors):
            assert (index, id, source_exclude_vectors) == ("features-v9", "example", False)
            return {"_source": doc, "_seq_no": 3, "_primary_term": 1}

        def update(self, **_kwargs):
            raise AssertionError("Existing vectors must not be rewritten")

    client = FakeES()
    selected = load_features(client, "features-v9", [("example", "country")])
    assert pending_texts(selected) == []
    assert apply_vectors(client, "features-v9", selected, {}) == 0


def test_apply_report_records_elapsed_time_without_reembedding(tmp_path, monkeypatch, capsys):
    vector = [1.0] + [0.0] * (DIMENSIONS - 1)
    doc = {"feature_id": "example", "kind": "country", "names": {"zh": "示例"},
           "literal_meanings": [{
               "translations": {lang: "central country" for lang in EMBEDDING_LANGUAGES},
               EMBEDDING_FIELD: {lang: vector for lang in EMBEDDING_LANGUAGES}}]}
    mapping = {"features-v9": {"mappings": {"properties": {"literal_meanings": {
        "properties": {EMBEDDING_FIELD: {"properties": {
            lang: {"dims": DIMENSIONS} for lang in EMBEDDING_LANGUAGES}}}}}}}}

    class FakeES:
        indices = SimpleNamespace(get_mapping=lambda **_kwargs: mapping)

        def get(self, **_kwargs):
            return {"_source": doc, "_seq_no": 1, "_primary_term": 1}

        def update(self, **_kwargs):
            raise AssertionError("Complete vectors must not be rewritten")

    monkeypatch.setattr("backend.embed_meanings.Settings.from_env",
                        lambda: SimpleNamespace(index="features-v9"))
    monkeypatch.setattr("backend.embed_meanings.read_plan", lambda _path: [("example", "country")])
    monkeypatch.setattr("backend.embed_meanings.connect", lambda _settings: nullcontext(FakeES()))
    monkeypatch.setattr("backend.embed_meanings.probe", lambda *_args: {"feature_id": "example"})
    args = SimpleNamespace(plan=tmp_path / "plan.json", output_dir=tmp_path,
                           force=False, apply=True, instruct=DEFAULT_INSTRUCT,
                           batch_size=20, probe_feature_id="example", probe_language="zh")
    logger = create_run_logger(tmp_path)
    try:
        run_job(args, logger, datetime.now(timezone.utc).isoformat(), time.perf_counter())
    finally:
        for handler in logger.handlers:
            handler.close()
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["pending_vectors"] == report["api_calls"] == report["updated_features"] == 0
    assert report["timing"]["total_seconds"] >= 0
    assert report["timing"]["api_seconds"] == 0
    assert report["timing"]["api_batches"] == []
    assert "ES update finished" in (tmp_path / "run.log").read_text(encoding="utf-8")
    assert json.loads(capsys.readouterr().out)["timing"] == report["timing"]
