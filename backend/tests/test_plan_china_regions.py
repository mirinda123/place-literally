import pytest

from backend.plan_china_regions import EXISTING, resolve_targets


def sample():
    regions = [{"short_label": f"Region {n}", "category": "province", "osm": f"node/{n}"}
               for n in range(1, 32)]
    expected = [(item["osm"], "state") for item in regions]
    expected.extend((osm, kind) for _, _, osm, kind in EXISTING)
    hits = [{"_source": {"feature_id": f"feature-{n}", "kind": kind,
                        "external_ids": {"osm": [osm]}}}
            for n, (osm, kind) in enumerate(expected)]
    return regions, hits


def test_resolves_all_34_unique_osm_labels():
    regions, hits = sample()
    targets = resolve_targets(regions, hits)
    assert len(targets) == len({item["feature_id"] for item in targets}) == 34
    assert sum(item["kind"] == "state" for item in targets) == 31


def test_missing_or_wrong_kind_label_blocks_batch():
    regions, hits = sample()
    with pytest.raises(ValueError, match="Missing"):
        resolve_targets(regions, hits[:-1])
    hits[0]["_source"]["kind"] = "city"
    with pytest.raises(ValueError, match="wrong-kind"):
        resolve_targets(regions, hits)
