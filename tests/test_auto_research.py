"""Offline regression tests for opt-in research; all public APIs and Gemini are mocked."""
from datetime import date
import json
from pathlib import Path
import socket
from types import SimpleNamespace

from google import genai
import httpx2
import pytest
from streamlit.testing.v1 import AppTest

from studio import auto_research, auto_research_ui
from studio.auto_research import AIResearchError, MODEL
from studio.db import Store
from studio.generator import PlanningContext
from studio.planning import generate_and_save
from studio.research import ResearchStore, today
from studio.gemini import GeminiConsent

CONSENT = GeminiConsent(True, True, True)


@pytest.fixture
def approved(tmp_path):
    store = Store(tmp_path / "ai.sqlite3")
    generate_and_save(store, PlanningContext(date(2026, 11, 9)))
    t = store.themes()[0]
    store.review(t["id"], t["version"], t["title"], t["outline"], "", "承認")
    return store, ResearchStore(store), t["id"]


def sample_candidates(n=8):
    return [{
        "id": f"node/{100+i}", "name": f"テストホテル{i}", "address": f"架空町{i}丁目",
        "official_url": f"https://example.org/hotel{i}", "source_url": f"https://www.openstreetmap.org/node/{100+i}",
        "description": "OSM候補", "price_note": "未確認", "source_label": "OpenStreetMap"
    } for i in range(n)]


def dummy_photo():
    return [{"label": "File:sample.jpg", "url": "https://commons.wikimedia.org/wiki/File:sample.jpg",
             "image_url": "https://upload.wikimedia.org/example.jpg", "owner": "Test Artist",
             "license": "CC BY-SA 4.0", "permission_status": "未確認"}]


def dummy_draft():
    candidates = sample_candidates()
    selected = [{**x, "reason": "公開データに住所とサイトが登録されています", "photos": dummy_photo()} for x in candidates[:5]]
    return {"theme": "架空ホテル5選", "area": "大阪市", "kind": "ホテル",
            "model": MODEL, "source": "OSM/Commons", "candidates": candidates, "selected": selected,
            "notice": "要確認"}


def test_discover_osm_from_public_records_without_inventing_facts(monkeypatch):
    calls = []
    def get(endpoint, params, **kwargs):
        calls.append((endpoint, params))
        if endpoint == auto_research.NOMINATIM:
            return [{"lat": "34.6800", "lon": "135.5100"}]
        return {"elements": [
            {"type": "node", "id": i, "tags": {
                "name": f"実在未確認のテスト施設{i}",
                "website": f"https://example.org/{i}",
                "addr:city": "大阪市", "addr:street": f"架空町{i}",
            }} for i in range(8)]}
    monkeypatch.setattr(auto_research, "_get_json", get)
    result = auto_research.discover_osm("大阪市", "ホテル")
    assert len(calls) == 2 and calls[0][0] == auto_research.NOMINATIM
    assert calls[1][0] == auto_research.OVERPASS
    assert len(result) == 8 and result[0]["source_url"].startswith("https://www.openstreetmap.org/node/")
    assert all(r["price_note"] == "未確認" for r in result)


@pytest.mark.parametrize("response", [[], [{"lat": "NaN", "lon": "135"}], [{"lat": "0", "lon": "0"}]])
def test_invalid_geocoding_never_searches_overpass(monkeypatch, response):
    calls = []
    def get(endpoint, params, **kwargs):
        calls.append(endpoint)
        return response
    monkeypatch.setattr(auto_research, "_get_json", get)
    with pytest.raises(AIResearchError):
        auto_research.discover_osm("大阪市", "ホテル")
    assert calls == [auto_research.NOMINATIM]


def test_gemini_selects_only_existing_five_ids_one_attempt(monkeypatch):
    calls, constructors = [], []
    actual_client = genai.Client
    def handler(request):
        calls.append(request)
        choices = [{"id": f"node/{100+i}", "reason": "出典があるので比較候補"} for i in range(5)]
        return httpx2.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [
            {"text": json.dumps({"picks": choices}, ensure_ascii=False)}]}, "finishReason": "STOP"}]})
    def client(**kwargs):
        constructors.append(kwargs)
        kwargs["http_options"].client_args = {"transport": httpx2.MockTransport(handler)}
        return actual_client(**kwargs)
    monkeypatch.setattr(genai, "Client", client)
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("Real network is forbidden"))
    results = auto_research.choose_with_gemini("ホテル5選", sample_candidates(), "test-only-synthetic-key", CONSENT)
    assert len(results) == 5 and len(calls) == 1
    assert constructors[0]["http_options"].retry_options.attempts == 1
    assert constructors[0]["http_options"].timeout == 120000
    cfg = json.loads(calls[0].content)["generationConfig"]
    assert cfg["thinkingConfig"] in ({"thinkingLevel": "MINIMAL"}, {"thinking_level": "MINIMAL"})
    assert cfg["responseMimeType"] == "application/json"
    assert "googleSearch" not in json.dumps(cfg)


def test_no_consent_rejects_gemini_before_loading_sdk(monkeypatch):
    monkeypatch.setattr(auto_research, "load_sdk", lambda: pytest.fail("No SDK allowed"))
    with pytest.raises(ValueError, match="無料枠"):
        auto_research.choose_with_gemini("ホテル5選", sample_candidates(), "test", GeminiConsent(False, True, True))


def test_commons_results_unverified_and_never_auto_license(monkeypatch):
    def get(endpoint, params, **kwargs):
        assert endpoint == auto_research.COMMONS
        return {"query": {"pages": {"1": {"title": "File:テスト施設.jpg",
            "imageinfo": [{"descriptionurl": "https://commons.wikimedia.org/wiki/File:Test.jpg",
                           "url": "https://upload.wikimedia.org/test.jpg",
                           "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"},
                                           "Artist": {"value": "<b>Artist</b>"}}}]}}}}
    monkeypatch.setattr(auto_research, "_get_json", get)
    photos = auto_research.commons_photos("テスト施設")
    assert len(photos) == 1 and photos[0]["owner"] == "Artist"
    assert photos[0]["permission_status"] == "未確認"


def test_ai_draft_stays_separate_then_atomic_import_with_unverified_photos(approved):
    store, research, theme_id = approved
    existing = list(research.facilities(theme_id))
    run = research.save_ai_draft(theme_id, dummy_draft())
    assert research.facilities(theme_id) == existing
    reopened = ResearchStore(Store(store.path))
    assert reopened.latest_ai_draft(theme_id)["id"] == run
    count = reopened.import_ai_draft(run)
    assert count == 5
    assert len(reopened.facilities(theme_id)) == 5
    for f in reopened.facilities(theme_id):
        assert "未確認" in f["notes"]
        assert reopened.sources(f["id"])[0]["label"] == "候補発見元"
        assert len(reopened.photos(f["id"])) == 1
        assert reopened.photos(f["id"])[0]["permission_status"] == "未確認"
        assert reopened.usable_photos(f["id"]) == []
    with pytest.raises(ValueError, match="登録済み"):
        reopened.import_ai_draft(run)


def test_revoking_approval_stops_import_and_preserves_original(approved):
    store, research, theme_id = approved
    run = research.save_ai_draft(theme_id, dummy_draft())
    theme = next(t for t in store.themes() if t["id"] == theme_id)
    store.review(theme_id, theme["version"], theme["title"], theme["outline"], "", "却下")
    with pytest.raises(ValueError, match="承認済み"):
        research.import_ai_draft(run)
    assert research.facilities(theme_id) == []


def test_build_research_never_invents_missing_photos(monkeypatch):
    monkeypatch.setattr(auto_research, "discover_osm", lambda a, k: sample_candidates())
    monkeypatch.setattr(auto_research, "choose_with_gemini",
                        lambda t, c, key, consent: [{**x, "reason": "選定"} for x in c[:5]])
    monkeypatch.setattr(auto_research, "commons_photos", lambda n: (_ for _ in ()).throw(AIResearchError("offline")))
    d = auto_research.build_research("ホテル5選", "大阪市", "ホテル", "synthetic", CONSENT)
    assert len(d["selected"]) == 5 and all(p["photos"] == [] for p in d["selected"])


def test_ui_requires_approval_before_any_secret_read_or_network(tmp_path, monkeypatch):
    monkeypatch.setenv("MAKASE_DB_PATH", str(tmp_path / "ui.sqlite3"))
    monkeypatch.setattr(auto_research_ui, "load_api_key", lambda: pytest.fail("Key must not be read"))
    monkeypatch.setattr(auto_research, "_get_json", lambda *a, **k: pytest.fail("Network forbidden"))
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20).run()
    at.sidebar.radio[0].set_value("AI投稿テーマ企画").run()
    next(b for b in at.button if b.label == "テーマ10案を作成").click().run()
    at.sidebar.radio[0].set_value("AI投稿テーマ企画").run()
    # Approve first generated theme and visit research.
    approve = next(b for b in at.button if b.label == "承認")
    approve.click().run()
    at.sidebar.radio[0].set_value("施設候補リサーチ").run()
    assert not at.exception
    generate = next(b for b in at.button if b.label == "公開データを調査してAIで5件選ぶ")
    generate.click().run()
    assert not at.exception and any("事前承認" in e.value for e in at.error)
