from io import BytesIO
import json
import urllib.error

import pytest

from scripts.collect_osm_cities import Overpass, build_query, population, select_reason, transform, validate
from scripts import collect_osm_cities as collector
from backend.import_countries import plan_import


@pytest.mark.parametrize("raw,expected", [("50000", 50000), ("50,000", 50000), ("50\u202f000", 50000),
    ("50 000", 50000), ("5万", None), ("50.000", None), ("12,34", None), (None, None)])
def test_population(raw, expected):
    assert population(raw) == expected


def test_selection_rules():
    assert select_reason({"place": "city"}) == "city_unknown_population"
    assert select_reason({"place": "town"}) is None
    assert select_reason({"place": "city", "population": "49999"}) is None
    assert select_reason({"place": "town", "population": "50,000"}) == "population_threshold"
    assert select_reason({"place": "village", "population": "500", "capital": "yes"}) == "national_capital"
    assert select_reason({"place": "town", "population": "500", "capital": "4"}) == "admin_level_4_capital"
    assert select_reason({"place": "village", "population": "100000"}) is None


def sample():
    return {"elements": [{"type": "node", "id": 1, "lon": 100, "lat": 30,
        "tags": {"place": "city", "name": "都市", "name:en": "City", "name:etymology": "ignored"}}]}


def test_country_scope_requires_one_matching_boundary():
    assert '(area.country)' in build_query("JP")
    with pytest.raises(ValueError):
        build_query('JP"')
    with pytest.raises(ValueError, match="boundary"):
        validate(sample(), "JP")
    payload = sample()
    payload["elements"].append({"type": "area", "tags": {"ISO3166-1": "JP"}})
    validate(payload, "JP")
    payload["elements"].append(payload["elements"][-1])
    with pytest.raises(ValueError, match="boundary"):
        validate(payload, "JP")


def test_deduplication_names_and_city_import_without_meanings():
    selected, stats = transform({"A": sample(), "B": sample()}, 50000)
    assert len(selected) == 1 and stats["target_language_coverage"]["en"] == 1
    assert selected[0]["names"] == {"en": "City"}
    assert selected[0]["query_scopes"] == ["A", "B"]
    actions, stats = plan_import(selected, [], "test", settlements=True)
    doc = actions[0]["_source"]
    assert doc["kind"] == "city" and doc["literal_meanings"] == [] and doc["literal_name"] is None
    doc["kind"] = "metropolis"
    hit = {"_id": doc["feature_id"], "_source": doc, "_seq_no": 1, "_primary_term": 1}
    assert plan_import(selected, [hit], "test", settlements=True)[0] == []
    doc["kind"] = selected[0]["kind"] = "state"
    assert plan_import(selected, [hit], "test", settlements=True)[0] == []


def test_rate_limit_wait_and_partial_response_rejection():
    waits, calls = [], []
    def opener(request, timeout):
        calls.append(request)
        if len(calls) == 1:
            raise urllib.error.HTTPError(request.full_url, 429, "busy", {"Retry-After": "60"}, None)
        response = BytesIO(json.dumps(sample()).encode())
        response.headers = {}
        return response
    Overpass(opener=opener, sleep=waits.append).fetch(build_query())
    assert waits[0] == 60 and len(calls) == 2
    with pytest.raises(ValueError, match="incomplete"):
        validate({**sample(), "remark": "Query timed out"})


def test_completed_caches_resume_and_failed_refresh_keeps_import_file(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["collector", "--output-dir", str(tmp_path)])
    calls = []
    def fetch(self, query, country):
        calls.append(query)
        return sample()
    monkeypatch.setattr(Overpass, "fetch", fetch)
    assert collector.main() == 0 and len(calls) == 3
    before = (tmp_path / "cities.json").read_bytes()
    def fail(*args):
        raise ValueError("Query timed out")
    monkeypatch.setattr(Overpass, "fetch", fail)
    assert collector.main() == 0
    monkeypatch.setattr("sys.argv", ["collector", "--output-dir", str(tmp_path), "--refresh"])
    assert collector.main() == 1
    assert (tmp_path / "cities.json").read_bytes() == before
    assert json.loads((tmp_path / "failed-run.json").read_text())["failures"]
