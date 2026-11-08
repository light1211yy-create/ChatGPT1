"""Model-policy tests use synthetic profiles and HTTP mocks, never Google API."""
from dataclasses import replace
from datetime import date
import json
from pathlib import Path
import socket

from google import genai
import httpx2
import pytest
from streamlit.testing.v1 import AppTest

from studio import gemini, gemini_models
from studio.db import Store
from studio.gemini import GeminiConsent, GeminiError, GeminiThemeGenerator, build_payload
from studio.gemini_models import ModelProfile, available_models
from studio.gemini_ui import GEMINI_MODE, TEST_MODE
from studio.generator import PlanningContext
from studio.planning import generate_and_save

CONTEXT = PlanningContext(date(2026, 11, 8), "おでかけ", "写真映えと保存を重視")
CONSENT = GeminiConsent(True, True, True)
APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture
def mock_sdk(monkeypatch):
    # The official SDK still serializes the request, but no socket may connect.
    real_client = genai.Client
    state = {"constructors": [], "requests": []}

    def handler(request):
        state["requests"].append(request)
        rows = [dict(title=f"モックの旅行企画{i}", category="おでかけ", score=80,
                     reason="写真映えの企画案。事実は要確認。", outline="比較の視点 → 後で施設選定 → 保存案内") for i in range(10)]
        return httpx2.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [
            {"text": json.dumps({"themes": rows}, ensure_ascii=False)}]}, "finishReason": "STOP"}]})

    def client(**kwargs):
        state["constructors"].append(kwargs)
        kwargs["http_options"].client_args = {"transport": httpx2.MockTransport(handler)}
        return real_client(**kwargs)

    monkeypatch.setattr(genai, "Client", client)
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("Real network forbidden"))
    return state


def test_production_has_no_officially_verified_models():
    assert gemini_models.VERIFIED_FREE_MODELS == {}
    assert available_models() == ()


@pytest.mark.parametrize("model", [None, "gemini-3.5-flash-lite", "gemini-2.5-flash-lite", "gemini-2.5-flash",
                                   "gemini-3.5-flash-lite-preview"])
def test_unverified_model_never_constructs_sdk_or_changes_existing_data(tmp_path, mock_sdk, model):
    store = Store(tmp_path / "protected.sqlite3")
    generate_and_save(store, CONTEXT)
    theme = store.themes()[0]
    store.review(theme["id"], theme["version"], theme["title"], theme["outline"], "保存済みの判断", "承認")
    before = (store.batches(), store.themes(), store.audit(theme["id"]))
    with pytest.raises(GeminiError):
        generate_and_save(store, CONTEXT, GeminiThemeGenerator(model=model, api_key="mock-only", consent=CONSENT))
    assert mock_sdk["constructors"] == mock_sdk["requests"] == []
    assert (store.batches(), store.themes(), store.audit(theme["id"])) == before


def test_ui_blocks_unverified_generation_and_can_return_to_test_mode(tmp_path, monkeypatch, mock_sdk):
    monkeypatch.setenv("MAKASE_DB_PATH", str(tmp_path / "ui.sqlite3"))

    def forbid_key_read():
        pytest.fail("No verified model: must not read a real key or secrets")

    monkeypatch.setattr("studio.gemini_ui.read_api_key", forbid_key_read)
    at = AppTest.from_file(str(APP), default_timeout=20).run()
    at.sidebar.radio[0].set_value("AI投稿テーマ企画").run()
    next(r for r in at.radio if r.label == "生成モード").set_value(GEMINI_MODE).run()
    assert not at.exception
    model = next(s for s in at.selectbox if s.label.startswith("Geminiモデル"))
    assert model.options == [] and model.value is None and model.disabled
    generate = next(b for b in at.button if b.label == "テーマ10案を作成")
    assert generate.disabled and len(at.checkbox) == 3
    assert any("確認できたモデルがありません" in e.value for e in at.error)
    for checkbox in at.checkbox:
        checkbox.check()
    # Also send a synthetic disabled-button trigger: the server guard must stop it.
    generate.click().run()
    assert not at.exception and Store().batches() == []
    assert mock_sdk["constructors"] == []
    next(r for r in at.radio if r.label == "生成モード").set_value(TEST_MODE).run()
    next(b for b in at.button if b.label == "テーマ10案を作成").click().run()
    assert not at.exception and len(Store().themes()) == 10
    assert mock_sdk["constructors"] == []


@pytest.mark.parametrize("level,tokens", [("MINIMAL", 1024), ("LOW", 4096)])
def test_sdk_serializes_explicit_level_without_legacy_budget(tmp_path, monkeypatch, mock_sdk, level, tokens):
    # This artificial ID is NOT an assertion that a real model accepts this level.
    profile = ModelProfile("fixture-level-model", tokens, None, level, date(2026, 11, 8), gemini_models.OFFICIAL_DOCS)
    monkeypatch.setattr(gemini_models, "VERIFIED_FREE_MODELS", {profile.model_id: profile})
    store = Store(tmp_path / "level.sqlite3")
    generate_and_save(store, CONTEXT, GeminiThemeGenerator(model=profile.model_id, api_key="mock-only", consent=CONSENT))
    assert len(mock_sdk["requests"]) == 1 and len(store.themes()) == 10
    body = json.loads(mock_sdk["requests"][0].content)
    cfg = body["generationConfig"]
    assert cfg["thinkingConfig"] in ({"thinkingLevel": level}, {"thinking_level": level})
    assert cfg["maxOutputTokens"] == tokens
    assert cfg["responseMimeType"] == "application/json" and cfg["responseJsonSchema"]["properties"]["themes"]["minItems"] == 10
    options = mock_sdk["constructors"][0]["http_options"]
    assert options.retry_options.attempts == 1 and options.timeout == 30000


@pytest.mark.parametrize("change", [
    {"max_output_tokens": 0}, {"max_output_tokens": True}, {"thinking_budget": True},
    {"thinking_budget": -1}, {"thinking_level": "MINIMAL"}, {"thinking_level": "unknown", "thinking_budget": None},
    {"source_urls": ()}, {"source_urls": None}, {"reviewed_on": "2026-11-08"},
    {"sdk_version": "999.0.0"}, {"model_id": "different-id"},
])
def test_invalid_model_profile_cannot_be_selected_or_sent(mock_reviewed_models, mock_sdk, change):
    model = "gemini-2.5-flash-lite"
    profile = replace(mock_reviewed_models[model], **change)
    gemini_models.VERIFIED_FREE_MODELS.clear()
    gemini_models.VERIFIED_FREE_MODELS[model] = profile
    assert available_models() == ()
    with pytest.raises(GeminiError, match="設定"):
        GeminiThemeGenerator(model=model, api_key="mock-only", consent=CONSENT)
    assert mock_sdk["constructors"] == []


@pytest.mark.parametrize("version", ["0.0.1", "3.0.1", "999.0.0"])
def test_unreviewed_sdk_version_stops_before_client(tmp_path, monkeypatch, mock_reviewed_models, mock_sdk, version):
    monkeypatch.setattr(gemini, "version", lambda name: version)
    store = Store(tmp_path / "version.sqlite3")
    with pytest.raises(GeminiError, match="バージョン"):
        generate_and_save(store, CONTEXT, GeminiThemeGenerator(api_key="mock-only", consent=CONSENT))
    assert store.batches() == [] and mock_sdk["constructors"] == []


def test_review_revoked_after_provider_creation_stops_before_sdk(tmp_path, mock_reviewed_models, mock_sdk):
    provider = GeminiThemeGenerator(api_key="mock-only", consent=CONSENT)
    mock_reviewed_models.clear()
    with pytest.raises(GeminiError):
        generate_and_save(Store(tmp_path / "revoked.sqlite3"), CONTEXT, provider)
    assert mock_sdk["constructors"] == []


def test_changed_model_settings_require_reconfirmation(tmp_path, mock_reviewed_models, mock_sdk):
    provider = GeminiThemeGenerator(api_key="mock-only", consent=CONSENT)
    model = provider.model
    mock_reviewed_models[model] = replace(mock_reviewed_models[model], max_output_tokens=4096)
    with pytest.raises(GeminiError, match="変更"):
        generate_and_save(Store(tmp_path / "changed.sqlite3"), CONTEXT, provider)
    assert mock_sdk["constructors"] == []


def test_makase_series_are_planning_formats_not_fabricated_facilities():
    payload = build_payload(CONTEXT, [], [])
    assert payload["preferred_series"] == ["ホテル5選", "レストラン5選", "旅行・おでかけ5選"]
    assert not payload["latest_web_verified"] and payload["performance_summary"] == []
