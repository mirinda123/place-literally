from copy import deepcopy

from backend.embed_all_meanings import apply_feature, inventory
from backend.indexing import EMBEDDING_FIELD


VECTOR = [1.0] + [0.0] * 511


def test_inventory_selects_only_existing_translations_without_vectors(monkeypatch):
    docs = [
        {"_source": {"feature_id": "country", "kind": "country", "literal_meanings": [
            {"translations": {"zh": "白色之地", "en": "white land"},
             EMBEDDING_FIELD: {"en": VECTOR}}]}},
        {"_source": {"feature_id": "city", "kind": "city", "literal_meanings": []}},
    ]
    def fake_scan(client, **kwargs):
        assert kwargs["source_exclude_vectors"] is False
        assert kwargs["index"] == "features-v9"
        return iter(docs)
    monkeypatch.setattr("backend.embed_all_meanings.scan", fake_scan)
    selected, counts, untranslated = inventory(object(), "features-v9")
    assert counts["all_features"] == 2
    assert counts["features_with_meanings"] == counts["meanings"] == 1
    assert counts["existing_vectors"] == counts["pending_vectors"] == 1
    assert selected[0]["pending"] == [(0, "zh", "白色之地")]
    assert {item["language"] for item in untranslated} == {"ja", "fr", "es"}


def test_apply_feature_keeps_existing_vectors_and_detects_changed_text():
    original = {"feature_id": "sample", "literal_meanings": [
        {"translations": {"zh": "白色之地", "en": "white land"},
         EMBEDDING_FIELD: {"en": VECTOR}, "editorial_note": "retain"}]}
    selected = {"feature_id": "sample", "translations": [original["literal_meanings"][0]["translations"]],
                "pending": [(0, "zh", "白色之地")]}

    class FakeES:
        def __init__(self):
            self.doc = deepcopy(original)
            self.patch = None

        def get(self, **kwargs):
            assert kwargs["source_exclude_vectors"] is False
            return {"_source": self.doc, "_seq_no": 7, "_primary_term": 2}

        def update(self, **kwargs):
            assert (kwargs["if_seq_no"], kwargs["if_primary_term"]) == (7, 2)
            self.patch = kwargs["doc"]

    es = FakeES()
    added, conflict = apply_feature(es, "features-v9", selected, {"白色之地": VECTOR})
    assert (added, conflict) == (1, None)
    saved = es.patch["literal_meanings"][0]
    assert set(saved[EMBEDDING_FIELD]) == {"zh", "en"}
    assert saved["editorial_note"] == "retain"
    assert es.doc == original

    es = FakeES()
    es.doc["literal_meanings"][0]["translations"]["zh"] = "已修改"
    assert apply_feature(es, "features-v9", selected, {"白色之地": VECTOR}) == (0, "translations_changed")
    assert es.patch is None
