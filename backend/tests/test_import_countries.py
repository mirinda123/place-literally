import pytest

from backend.import_countries import plan_import
from backend.indexing import documents


def country():
    return {"osm": "node/123", "local_name": "中国", "names": {"en": "China", "fr": "Chine"},
            "location": {"lon": 108, "lat": 34}}


def test_new_country_has_identity_and_no_invented_meaning():
    actions, stats = plan_import([country()], [], "features-v1")
    doc = actions[0]["_source"]
    assert actions[0]["_op_type"] == "create"
    assert doc["external_ids"]["osm"] == ["node/123"]
    assert doc["names"] == {"en": "China", "fr": "Chine", "und": "中国"}
    assert doc["literal_name"] is None and doc["literal_meanings"] == [] and doc["meaning_id"] is None
    assert stats == {"created": 1, "updated": 0, "unchanged": 0}


def test_merge_keeps_existing_id_curated_names_and_meaning_then_is_idempotent():
    existing = documents([{"feature_id": "china-cn", "kind": "country", "names": {"en": "Curated China"},
        "location": {"lon": 109, "lat": 35}, "external_ids": {"osm": ["node/123"]},
        "literal_name": {"text": "中国", "lang": "zh"}, "literal_meanings": [{"translations": {"en": "Central country"}}],
        "meaning_id": "central-country"}])[0]
    hit = {"_id": "china-cn", "_source": existing, "_seq_no": 1, "_primary_term": 2}
    actions, stats = plan_import([country()], [hit], "features-v1")
    action = actions[0]
    assert action["if_seq_no"] == 1 and action["if_primary_term"] == 2
    assert action["_id"] == "china-cn" and stats["updated"] == 1
    assert action["_source"]["names"]["en"] == "Curated China"
    assert action["_source"]["names"]["fr"] == "Chine"
    for field in ("feature_id", "location", "literal_name", "literal_meanings", "meaning_id"):
        assert action["_source"][field] == existing[field]
    actions, stats = plan_import([country()], [{**hit, "_source": action["_source"]}], "features-v1")
    assert actions == [] and stats["unchanged"] == 1


def test_conflicts_abort_before_writing():
    with pytest.raises(ValueError, match="Duplicate input"):
        plan_import([country(), country()], [], "features-v1")
    hit = {"_id": "a", "_source": {"external_ids": {"osm": ["node/123"]}}}
    with pytest.raises(ValueError, match="Ambiguous"):
        plan_import([country()], [hit, {**hit, "_id": "b"}], "features-v1")
    with pytest.raises(ValueError, match="already belongs"):
        plan_import([country()], [{"_id": "osm-node-123", "_source": {}}], "features-v1")


def test_region_import_keeps_state_identity_and_rejects_city_collision():
    region = {**country(), "kind": "state"}
    actions, stats = plan_import([region], [], "features-v4", regions=True)
    assert stats["created"] == 1
    assert actions[0]["_source"]["kind"] == "state"
    assert actions[0]["_source"]["external_ids"]["osm"] == ["node/123"]
    city = {"_id": "existing-city", "_source": {"kind": "city", "external_ids": {"osm": ["node/123"]}}}
    with pytest.raises(ValueError, match="another feature kind"):
        plan_import([region], [city], "features-v4", regions=True)
