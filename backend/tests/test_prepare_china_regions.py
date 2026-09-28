import pytest

from backend.indexing import documents
from backend.prepare_china_regions import patch_for


def state():
    return documents([{"feature_id": "anhui", "kind": "state",
        "names": {"zh": "安徽省", "zh-Hans": "安徽省", "en": "Anhui Province"},
        "location": {"lon": 117, "lat": 32}, "external_ids": {"osm": ["node/123"]}}])[0]


def test_pin_attested_simplified_chinese_name():
    patch = patch_for(state())
    assert patch == {"literal_name": {"text": "安徽省", "lang": "zh-Hans"}}


def test_existing_meaning_cannot_change_basis_without_explicit_reset():
    doc = state()
    doc["literal_name"] = {"text": "安徽", "lang": "gan"}
    doc["literal_meanings"] = [{"translations": {"zh": "错误释义"}}]
    with pytest.raises(ValueError, match="different original"):
        patch_for(doc)
    patch = patch_for(doc, reset=True)
    assert patch == {"literal_name": {"text": "安徽省", "lang": "zh-Hans"},
                     "literal_meanings": []}
