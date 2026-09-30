import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import uuid
from dataclasses import replace

import pytest

from backend.config import Settings, connect
from backend.indexing import documents, import_seed
from backend.translate_meanings import (apply_result, cache_key, call_codex, merge_result,
    needs_work, output_schema, parse_languages, payload_for, validate_result)


@pytest.fixture
def doc():
    return documents([{"feature_id": "test-country", "kind": "country", "names": {"zh": "中国", "en": "China", "und": "中国"},
        "location": {"lon": 108, "lat": 34}, "external_ids": {"osm": ["node/123"]},
        "literal_name": {"text": "中国", "lang": "zh"},
        "literal_meanings": [{"translations": {"en": "central country"}}], "meaning_id": "central-country"}])[0]


def ready(payload):
    meanings = {"zh": "中央之国", "en": "central country", "ja": "中央の国"}
    return {"feature_id": payload["feature_id"], "status": "ready",
        "literal_name": payload["literal_name"] or {"text": "中国", "lang": "zh"},
        "literal_meanings": [{"translations": {lang: meanings.get(lang, "central country") for lang in payload["target_languages"]}}],
        "note": "Test draft"}


def test_existing_meanings_are_rechecked_and_corrections_clear_stale_group(doc):
    doc["literal_meanings"][0]["translations"]["en"] = "an old incorrect gloss"
    payload = payload_for(doc, ["zh", "en", "ja"])
    assert payload["target_languages"] == ["zh", "en", "ja"]
    patch = merge_result(doc, payload, ready(payload))
    assert patch["literal_meanings"][0]["translations"]["en"] == "central country"
    assert patch["literal_meanings"][0]["translations"]["ja"] == "中央の国"
    assert patch["meaning_id"] is None
    assert doc["literal_meanings"] == [{"translations": {"en": "an old incorrect gloss"}}]


def test_completed_places_need_explicit_review_existing(doc):
    assert not needs_work(doc, ["en"])
    assert needs_work(doc, ["en"], review_existing=True)
    assert needs_work(doc, ["zh", "en"])


@pytest.mark.parametrize("change", ["identity", "language", "source", "empty", "long", "paragraph", "filler", "extra", "status"])
def test_reject_malformed_or_semantically_misaligned_outputs(doc, change):
    payload = payload_for(doc, ["zh"])
    result = ready(payload)
    if change == "identity": result["feature_id"] = "different"
    if change == "language": result["literal_meanings"] = [{"translations": {"fr": "pays"}}]
    if change == "source": result["literal_name"] = {"text": "China", "lang": "en"}
    if change == "empty": result["literal_meanings"][0]["translations"]["zh"] = " "
    if change == "long": result["literal_meanings"][0]["translations"]["zh"] = "地名的字面解释" * 50
    if change == "paragraph": result["literal_meanings"][0]["translations"]["zh"] = "第一句。\n第二句。"
    if change == "filler": result["literal_meanings"][0]["translations"]["zh"] = "可能意为中央之国"
    if change == "extra": result["names"] = {}
    if change == "status": result["status"] = "guess"
    with pytest.raises(ValueError): validate_result(result, payload)


def test_uncertainty_never_becomes_a_published_translation(doc):
    payload = payload_for(doc, ["zh"])
    result = {**ready(payload), "status": "uncertain", "literal_name": None, "literal_meanings": []}
    assert merge_result(doc, payload, result) is None
    result["literal_meanings"] = [{"translations": {"zh": "unknown"}}]
    with pytest.raises(ValueError): validate_result(result, payload)


def test_multiple_meanings_are_separate_and_aligned_by_language(doc):
    payload = payload_for(doc, ["zh", "en"])
    result = ready(payload)
    result["literal_meanings"].append({"translations": {"zh": "中部地区", "en": "central region"}})
    patch = merge_result(doc, payload, result)
    assert [m["translations"]["zh"] for m in patch["literal_meanings"]] == ["中央之国", "中部地区"]
    assert patch["meaning_id"] is None
    assert len(output_schema(["zh", "en"])["properties"]["literal_meanings"]["items"]["properties"]["translations"]["required"]) == 2


def test_new_original_must_match_supplied_name(doc):
    doc.update(literal_name=None, literal_meanings=[], meaning_id=None)
    payload = payload_for(doc, ["zh"])
    result = ready(payload)
    validate_result(result, payload)
    result["literal_name"] = {"text": "made-up name", "lang": "zh"}
    with pytest.raises(ValueError): validate_result(result, payload)


def test_stale_drafts_do_not_overwrite_concurrent_edits(doc):
    payload = payload_for(doc, ["zh"])
    changed = copy.deepcopy(doc)
    changed["literal_meanings"][0]["translations"]["en"] = "edited meaning"
    with pytest.raises(ValueError, match="changed"):
        merge_result(changed, payload, ready(payload))


def test_cache_is_bound_to_model_prompt_input_and_target_languages(doc):
    payload = payload_for(doc, ["zh"])
    key = cache_key(payload, "model-a", "prompt")
    assert key != cache_key(payload, "model-b", "prompt")
    assert key != cache_key(payload, "model-a", "prompt-v2")
    assert key != cache_key(payload_for(doc, ["ja"]), "model-a", "prompt")
    assert key != cache_key(payload, "model-a", "prompt", "medium")


def test_cli_uses_stdin_and_schema_in_an_isolated_directory(monkeypatch, doc):
    payload = payload_for(doc, ["zh"])
    monkeypatch.setenv("ES_PASSWORD", "test-secret")
    def run(command, **kwargs):
        assert command[:3] == ["codex.exe", "--search", "exec"] and command[-1] == "-"
        assert command[command.index("--model") + 1] == "chosen-model"
        assert command[command.index("-c") + 1] == 'model_reasoning_effort="xhigh"'
        assert command[command.index("--sandbox") + 1] == "workspace-write"
        assert "--ignore-user-config" in command
        assert kwargs["shell"] is False and "ES_PASSWORD" not in kwargs["env"]
        assert payload["feature_id"] in kwargs["input"]
        schema = json.loads(Path(command[command.index("--output-schema") + 1]).read_text())
        assert schema == output_schema(payload["target_languages"])
        Path(command[command.index("--output-last-message") + 1]).write_text(json.dumps(ready(payload)), encoding="utf-8")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr("backend.translate_meanings.subprocess.run", run)
    assert call_codex("codex.exe", payload, "chosen-model", "prompt", 30) == ready(payload)


def test_failed_cli_cannot_reuse_output(monkeypatch, doc):
    monkeypatch.setattr("backend.translate_meanings.subprocess.run", lambda *a, **kw: SimpleNamespace(returncode=1))
    with pytest.raises(RuntimeError, match="exited"):
        call_codex("codex", payload_for(doc, ["zh"]), None, "prompt", 30)


def test_language_parameter_validation():
    assert parse_languages("zh,en,ja,fr,es") == ["zh", "en", "ja", "fr", "es"]
    import argparse
    for invalid in ["", "zh,zh", "zh,*", "zh,", "zh.bad"]:
        with pytest.raises(argparse.ArgumentTypeError): parse_languages(invalid)


def test_apply_to_live_es_preserves_identity_and_saves_backup(doc, tmp_path):
    if os.getenv("RUN_ES_TESTS") != "1": pytest.skip("Set RUN_ES_TESTS=1")
    settings = replace(Settings.from_env(), index="literal-name-map-test-" + uuid.uuid4().hex)
    with connect(settings) as client:
        try:
            import_seed(client, settings, [doc])
            payload = payload_for(doc, ["zh"])
            apply_result(client, settings, doc["feature_id"], payload, ready(payload), tmp_path)
            saved = client.get(index=settings.index, id=doc["feature_id"])["_source"]
            for field in ["names", "location", "external_ids", "meaning_id", "literal_name"]:
                assert saved[field] == doc[field]
            assert saved["literal_meanings"] == [{"translations": {"en": "central country", "zh": "中央之国"}}]
            backup = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
            assert backup["_source"] == doc
            with pytest.raises(ValueError, match="changed"):
                apply_result(client, settings, doc["feature_id"], payload, ready(payload), tmp_path)
            current = client.get(index=settings.index, id=doc["feature_id"])["_source"]
            correction_payload = payload_for(current, ["en"])
            correction = ready(correction_payload)
            correction["literal_meanings"][0]["translations"]["en"] = "country at the center"
            apply_result(client, settings, doc["feature_id"], correction_payload, correction,
                         tmp_path / "correction")
            corrected = client.get(index=settings.index, id=doc["feature_id"])["_source"]
            assert corrected["literal_meanings"] == [{"translations": {"en": "country at the center", "zh": "中央之国"}}]
            assert corrected["meaning_id"] is None
            assert corrected["external_ids"] == doc["external_ids"]
            assert json.loads(next((tmp_path / "correction").glob("*.json")).read_text(encoding="utf-8"))["_source"] == current
        finally:
            assert settings.index.startswith("literal-name-map-test-")
            client.indices.delete(index=settings.index, ignore_unavailable=True)
