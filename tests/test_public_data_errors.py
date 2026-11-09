"""No-network regression tests for public-data failure diagnostics and manual server selection."""
import io
from urllib.error import HTTPError, URLError

import pytest

from studio import auto_research as api


@pytest.mark.parametrize("endpoint,label", [
    (api.NOMINATIM, "Nominatim"),
    (api.OVERPASS, "FOSSGIS"),
    (api.OVERPASS_PRIVATE_COFFEE, "Private.coffee"),
    (api.COMMONS, "Wikimedia Commons"),
])
def test_http_503_identifies_stage_without_leaking_url(monkeypatch, endpoint, label):
    count = []
    def fail(request, timeout=0):
        count.append(request)
        raise HTTPError(request.full_url, 503, "fake response contains private content", {}, io.BytesIO(b"private"))
    monkeypatch.setattr(api, "urlopen", fail)
    with pytest.raises(api.AIResearchError) as error:
        api._get_json(endpoint, {"q": "sensitive-query-text"})
    message = str(error.value)
    assert label in message and "HTTP 503" in message
    assert "sensitive-query-text" not in message and "private content" not in message
    assert len(count) == 1  # Never automatic retry.


@pytest.mark.parametrize("status", [403, 406, 429, 408, 502, 504])
def test_error_status_is_safe_and_explained(monkeypatch, status):
    def fail(request, timeout=0):
        raise HTTPError(request.full_url, status, "bad", {}, None)
    monkeypatch.setattr(api, "urlopen", fail)
    with pytest.raises(api.AIResearchError) as error:
        api._get_json(api.NOMINATIM, {"q": "大阪"})
    assert f"HTTP {status}" in str(error.value)
    assert "自動再試行" in str(error.value)


def test_connection_error_explains_provider_and_no_raw_details(monkeypatch):
    count = []
    def fail(request, timeout=0):
        count.append(request)
        raise URLError("raw private network hostname")
    monkeypatch.setattr(api, "urlopen", fail)
    with pytest.raises(api.AIResearchError) as error:
        api._get_json(api.OVERPASS, {"data": "secret-query"})
    assert "Overpass / FOSSGIS" in str(error.value)
    assert "raw private" not in str(error.value)
    assert len(count) == 1


def test_invalid_json_identifies_endpoint(monkeypatch):
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self, count): return b"<html>Overloaded</html>"
    monkeypatch.setattr(api, "urlopen", lambda request, timeout=0: Response())
    with pytest.raises(api.AIResearchError, match="JSON形式"):
        api._get_json(api.OVERPASS, {"data": "fake"})


def test_user_selected_overpass_provider_one_request_without_fallback(monkeypatch):
    calls = []
    def fake(endpoint, params, **kwargs):
        calls.append(endpoint)
        if endpoint == api.NOMINATIM:
            return [{"lat": "34.6800", "lon": "135.5100"}]
        return {"elements": [{
            "type": "node", "id": 100 + i, "tags": {
                "name": f"架空ホテル{i}", "addr:city": "大阪市",
                "website": f"https://example.org/{i}",
            }
        } for i in range(5)]}
    monkeypatch.setattr(api, "_get_json", fake)
    candidates = api.discover_osm("大阪市", "ホテル", overpass_endpoint=api.OVERPASS_PRIVATE_COFFEE)
    assert len(candidates) == 5
    assert calls == [api.NOMINATIM, api.OVERPASS_PRIVATE_COFFEE]


def test_reject_unapproved_public_server_before_network(monkeypatch):
    monkeypatch.setattr(api, "_get_json", lambda *a, **k: pytest.fail("No external requests"))
    with pytest.raises(api.AIResearchError, match="選択が不正"):
        api.discover_osm("大阪", "ホテル", overpass_endpoint="https://example.com/")
    with pytest.raises(api.AIResearchError, match="選択が不正"):
        api.build_research("ホテル5選", "大阪", "ホテル", "fake", None,
                           overpass_endpoint="https://example.com/")


def test_common_photo_lookup_failure_remains_optional(monkeypatch):
    monkeypatch.setattr(api, "discover_osm", lambda a, k: [{
        "id": f"node/{100+i}", "name": f"架空ホテル{i}", "official_url": "",
        "address": "", "source_url": f"https://www.openstreetmap.org/node/{100+i}"
    } for i in range(5)])
    monkeypatch.setattr(api, "choose_with_gemini", lambda *args: [
        {**x, "reason": "比較対象"} for x in api.discover_osm("大阪", "ホテル")
    ])
    monkeypatch.setattr(api, "commons_photos", lambda *args: (_ for _ in ()).throw(api.AIResearchError("写真検索不可")))
    from studio.gemini import GeminiConsent
    doc = api.build_research("ホテル5選", "大阪", "ホテル", "fake", GeminiConsent(True, True, True))
    assert len(doc["selected"]) == 5
    assert all(c["photos"] == [] for c in doc["selected"])
