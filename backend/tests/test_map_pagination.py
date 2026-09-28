import os
import uuid
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings, connect
from backend.indexing import import_seed
from backend.main import create_app


def test_map_cursor_crosses_ten_thousand_and_keeps_full_detail_names():
    if os.getenv("RUN_ES_TESTS") != "1":
        pytest.skip("Set RUN_ES_TESTS=1")
    settings = replace(Settings.from_env(), index="literal-name-map-test-" + uuid.uuid4().hex)
    docs = [{"feature_id": f"node-{i:05}", "kind": "city", "names": {"en": f"City {i}", "de": "Stadt", "und": "Local"},
             "location": {"lon": 1, "lat": 2}} for i in range(10005)]
    with connect(settings) as client:
        try:
            import_seed(client, settings, docs)
            with TestClient(create_app(settings)) as api:
                ids, after = [], None
                while True:
                    result = api.get("/api/map-features", params={"after": after} if after else {})
                    assert result.status_code == 200, result.text
                    page = result.json()
                    assert page["total"] == 10005
                    assert all("de" not in item["names"] for item in page["results"])
                    ids.extend(item["feature_id"] for item in page["results"])
                    after = page["next_after"]
                    if after is None:
                        break
                assert len(ids) == len(set(ids)) == 10005
                assert api.get("/api/features/node-00000").json()["names"]["de"] == "Stadt"
        finally:
            client.indices.delete(index=settings.index, ignore_unavailable=True)
