import copy

import pytest

from scripts.collect_osm_china_regions import REGIONS, transform


def payload():
    labels = [label for group in REGIONS.values() for label in group]
    return {"elements": [{"type": "node", "id": i, "lat": 30, "lon": 110,
            "tags": {"place": "state", "name": label + "省", "name:zh": label + "省"}}
            for i, label in enumerate(labels, 1)]}


def test_selects_only_unambiguous_expected_state_labels():
    regions = transform(payload())
    assert len(regions) == 31
    assert {region["kind"] for region in regions} == {"state"}
    assert len({region["osm"] for region in regions}) == 31


def test_missing_or_duplicate_label_blocks_export():
    missing = payload()
    missing["elements"].pop()
    with pytest.raises(ValueError, match="Expected one"):
        transform(missing)
    duplicate = payload()
    duplicate["elements"].append(copy.deepcopy(duplicate["elements"][0]))
    duplicate["elements"][-1]["id"] = 999
    with pytest.raises(ValueError, match="Expected one"):
        transform(duplicate)
