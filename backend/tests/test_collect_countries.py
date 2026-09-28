import json
from io import BytesIO
import urllib.error

import pytest

from scripts import collect_osm_countries as collector


def sample():
    return {"osm3s": {"timestamp_osm_base": "2026-09-20T00:00:00Z"}, "elements": [
        {"type": "node", "id": 101, "lat": 30, "lon": 100, "tags": {
            "place": "country", "name": "原名", "ISO3166-1:alpha2": "XX", "name:zh": "中文",
            "name:en": "Example", "name:fr": "Exemple", "name:ja": "例", "name:ko": "예",
            "name:zh-Hant": "範例", "name:etymology": "Not a language", "name:en:pronunciation": "..."}},
        {"type": "node", "id": 102, "lat": 31, "lon": 101, "tags": {
            "place": "country", "name": "Other", "ISO3166-1:alpha2": "XX"}},
    ]}


def test_preserve_names_without_fabricating_translations_or_merging_countries():
    countries, report = collector.transform(sample())
    assert len(countries) == 2
    first = countries[0]
    assert first["osm"] == "node/101"
    assert first["names"]["zh"] == "中文"
    assert "zh-Hans" not in first["names"]
    assert "zh-Hans" in first["missing_languages"]
    assert "etymology" not in first["names"]
    assert first["name_tags"]["name:etymology"] == "Not a language"
    assert report["duplicate_country_codes"] == {"XX": ["node/101", "node/102"]}
    assert report["target_language_coverage"]["en"] == 1


@pytest.mark.parametrize("change", [
    lambda p: p.update(remark="runtime error: Query timed out"),
    lambda p: p.update(elements=[]),
    lambda p: p["elements"].append(p["elements"][0]),
    lambda p: p["elements"][0].update(lat=999),
])
def test_reject_partial_or_invalid_results(change):
    payload = sample()
    change(payload)
    with pytest.raises(ValueError):
        collector.transform(payload)


def test_retry_rate_limit_then_success():
    calls, waits = [], []
    def opener(request, timeout):
        calls.append(request)
        if len(calls) == 1:
            raise urllib.error.HTTPError(request.full_url, 429, "busy", {"Retry-After": "45"}, None)
        return BytesIO(json.dumps(sample()).encode())
    collector.fetch_countries(collector.ENDPOINT, opener=opener, sleep=waits.append)
    assert len(calls) == 2 and waits == [45]
    assert calls[0].get_method() == "POST"


def test_partial_http_200_is_not_retried_or_accepted():
    def opener(*args, **kwargs):
        return BytesIO(b'{"remark":"runtime error", "elements":[]}')
    with pytest.raises(ValueError):
        collector.fetch_countries(collector.ENDPOINT, opener=opener, sleep=lambda _: pytest.fail("Unexpected retry"))


def test_cached_run_is_offline_and_failed_refresh_preserves_files(tmp_path, monkeypatch):
    monkeypatch.setattr(collector, "fetch_countries", lambda *args: sample())
    first = collector.collect(tmp_path)
    raw = (tmp_path / "overpass-countries.raw.json").read_bytes()
    countries = (tmp_path / "countries.json").read_bytes()
    def fail(*args):
        raise ValueError("Invalid server response")
    monkeypatch.setattr(collector, "fetch_countries", fail)
    second = collector.collect(tmp_path)
    assert not first["used_cache"] and second["used_cache"]
    with pytest.raises(ValueError):
        collector.collect(tmp_path, refresh=True)
    assert (tmp_path / "overpass-countries.raw.json").read_bytes() == raw
    assert (tmp_path / "countries.json").read_bytes() == countries
