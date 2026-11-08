"""Gemini 3.8 Flash registry / serialized request checks, no live calls."""
from datetime import date
import json
from pathlib import Path

from google import genai
from google.genai import types
import httpx2
import pytest
from streamlit.testing.v1 import AppTest

from studio import gemini_models
from studio.db import Store
from studio.gemini import GeminiConsent, GeminiThemeGenerator
from studio.generator import PlanningContext
from studio.planning import generate_and_save

MODEL = "gemini-3.8-flash"
APP = Path(__file__).resolve().parents[1] / "app.py"


def test_verified_default_profile():
    assert gemini_models.DEFAULT_MODEL_ID == MODEL
    assert gemini_models.available_models() == (MODEL, "gemini-3.5-flash-lite")
    profile = gemini_models.model_profile()
    assert profile.model_id == MODEL
    assert profile.thinking_level == "MEDIUM"
    assert profile.thinking_budget is None
    assert profile.reviewed_on == date(2026, 11, 9)
    assert profile.confirmation_source == "developer_review"


def test_sdk_request_uses_medium_and_omits_candidate_count(tmp_path, monkeypatch):
    real_client = genai.Client
    requests = []
    def handler(request):
        requests.append(request)
        themes = [
            {"title": f"モック3.8企画{i}", "category": "おでかけ",
             "score": 80, "reason": "実在施設の確認は後で行います",
             "outline": "施設比較の構成案"}
            for i in range(10)
        ]
        return httpx2.Response(200, json={
            "candidates": [{
                "content": {"role": "model", "parts": [{"text": json.dumps({"themes": themes}, ensure_ascii=False)}]},
                "finishReason": "STOP"
            }],
            "modelVersion": MODEL
        })

    def fake_client(**kwargs):
        kwargs["http_options"].client_args = {"transport": httpx2.MockTransport(handler)}
        return real_client(**kwargs)

    monkeypatch.setattr(genai, "Client", fake_client)
    store = Store(tmp_path / "gemini38.sqlite3")
    context = PlanningContext(date(2026, 11, 9), "おでかけ")
    provider = GeminiThemeGenerator(
        api_key="mock-only-key", consent=GeminiConsent(True, True, True)
    )
    generate_and_save(store, context, provider)
    assert len(requests) == 1
    request = requests[0]
    assert f"{MODEL}:generateContent" in str(request.url)
    payload = json.loads(request.content)
    config = payload["generationConfig"]
    assert config["thinkingConfig"] in ({"thinkingLevel": "MEDIUM"}, {"thinking_level": "MEDIUM"})
    assert "candidateCount" not in config and "candidate_count" not in config
    assert "thinkingBudget" not in config["thinkingConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["responseJsonSchema"]["properties"]["themes"]["minItems"] == 10
    assert len(store.themes()) == 10


def test_ui_default_is_38_without_reading_key(tmp_path, monkeypatch):
    monkeypatch.setenv("MAKASE_DB_PATH", str(tmp_path / "ui.sqlite3"))
    import studio.gemini_ui as ui
    monkeypatch.setattr(ui, "read_api_key", lambda: pytest.fail("key must not be read"))
    at = AppTest.from_file(str(APP), default_timeout=20).run()
    at.sidebar.radio[0].set_value("AI投稿テーマ企画").run()
    next(r for r in at.radio if r.label == "生成モード").set_value(ui.GEMINI_MODE).run()
    selection = next(s for s in at.selectbox if s.label.startswith("Geminiモデル"))
    assert selection.value == MODEL
    assert selection.options == [MODEL, "gemini-3.5-flash-lite"]
    assert not at.exception
