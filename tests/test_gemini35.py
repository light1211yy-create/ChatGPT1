"""Gemini 3.5 profile and SDK tests: synthetic keys, HTTP mocks, temp DBs only."""
from datetime import date
import itertools
import json
from pathlib import Path
import socket
from types import SimpleNamespace

from google import genai
from google.genai import types
import httpx2
import pytest
from streamlit.testing.v1 import AppTest

from studio import gemini, gemini_models, gemini_ui
from studio.db import Store
from studio.gemini import GeminiConsent, GeminiError, GeminiThemeGenerator
from studio.generator import PlanningContext
from studio.planning import generate_and_save

MODEL = "gemini-3.5-flash-lite"
KEY = "mock-gemini35-key"
CONTEXT = PlanningContext(date(2026, 11, 9), "おでかけ", "写真映えと保存を重視")
CONSENT = GeminiConsent(True, True, True)
APP = Path(__file__).resolve().parents[1] / "app.py"


def mock_output():
    return json.dumps({"themes": [dict(title=f"モック3.5企画{i}", category="おでかけ" if i % 2 else "グルメ",
        score=80+i, reason="季節の提案。施設・価格は公式出典で後から確認。", outline="写真2枚と比較ポイント → 保存案内")
        for i in range(10)]}, ensure_ascii=False)


@pytest.fixture
def sdk(monkeypatch):
    real_client = genai.Client
    state = SimpleNamespace(requests=[], constructors=[], status=200, text=mock_output(),
                            finish="STOP", exception=None, key_reads=0)

    def handler(request):
        state.requests.append(request)
        if state.exception:
            raise state.exception
        if state.status != 200:
            return httpx2.Response(state.status, json={"error": {"code": state.status, "message": KEY + " mock private error"}})
        return httpx2.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": state.text}]},
            "finishReason": state.finish}], "modelVersion": MODEL})

    def client(**kwargs):
        state.constructors.append(kwargs)
        kwargs["http_options"].client_args = {"transport": httpx2.MockTransport(handler)}
        return real_client(**kwargs)

    monkeypatch.setattr(genai, "Client", client)
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("Real network forbidden"))
    return state


def test_user_confirmed_production_profile_is_only_default_model():
    assert gemini_models.available_models() == ("gemini-3.8-flash", MODEL)
    profile = gemini_models.model_profile(MODEL)
    assert profile.model_id == MODEL and profile.confirmation_source == "user_confirmation"
    assert profile.reviewed_on == date(2026, 11, 9)
    assert profile.thinking_level == "MINIMAL" and profile.thinking_budget is None
    assert profile.max_output_tokens == 8192 and profile.sdk_version == "3.0.0"
    assert profile.source_urls == (
        "https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite",
        "https://ai.google.dev/gemini-api/docs/pricing",
        "https://ai.google.dev/gemini-api/docs/thinking",
    )
    # SDK-side typing only; this does not contact the real model.
    cfg = types.ThinkingConfig(thinking_level=profile.thinking_level)
    assert cfg.thinking_level == types.ThinkingLevel.MINIMAL and cfg.thinking_budget is None


def test_real_sdk_serializes_default_model_minimal_schema_and_safe_options(tmp_path, sdk):
    store = Store(tmp_path / "sdk.sqlite3")
    provider = GeminiThemeGenerator(model=MODEL, api_key=KEY, consent=CONSENT)
    batch = generate_and_save(store, CONTEXT, provider)
    assert len(sdk.requests) == len(sdk.constructors) == 1
    request = sdk.requests[0]
    assert request.url.host == "generativelanguage.googleapis.com" and f"{MODEL}:generateContent" in str(request.url)
    assert "key=" not in str(request.url) and request.headers["x-goog-api-key"] == KEY
    body = json.loads(request.content)
    config = body["generationConfig"]
    assert config["thinkingConfig"] in ({"thinkingLevel": "MINIMAL"}, {"thinking_level": "MINIMAL"})
    assert config["maxOutputTokens"] == 8192 and config["responseMimeType"] == "application/json"
    assert config["responseJsonSchema"]["properties"]["themes"]["minItems"] == 10
    assert config["responseJsonSchema"]["properties"]["themes"]["maxItems"] == 10
    assert body["tools"] == [] and "googleSearch" not in json.dumps(body)
    options = sdk.constructors[0]["http_options"]
    assert options.retry_options.attempts == 1 and options.timeout == 30000
    assert sdk.constructors[0]["vertexai"] is False and sdk.constructors[0]["enterprise"] is False
    reopened = Store(store.path)
    assert len(reopened.themes(batch)) == 10
    assert MODEL in reopened.batches()[0]["provider"] and reopened.batches()[0]["created_at"].endswith("+09:00")
    assert KEY not in json.dumps(reopened.batches())


@pytest.mark.parametrize("model", ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-3.5-pro", "gemini-3.5-flash-lite-preview"])
def test_legacy_paid_and_unregistered_variants_are_not_fallbacks(sdk, model):
    with pytest.raises(GeminiError, match="対象外"):
        GeminiThemeGenerator(model=model, api_key=KEY, consent=CONSENT)
    assert sdk.requests == sdk.constructors == []


@pytest.mark.parametrize("checks", [v for v in itertools.product((False, True), repeat=3) if not all(v)])
def test_incomplete_consent_cannot_even_read_environment_key(tmp_path, monkeypatch, sdk, checks):
    original_get = gemini.os.environ.get

    def guard(name, *args):
        if name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            pytest.fail("API key must not be read before consent")
        return original_get(name, *args)

    monkeypatch.setattr(gemini.os.environ, "get", guard)
    provider = GeminiThemeGenerator(model=MODEL, consent=GeminiConsent(*checks))
    store = Store(tmp_path / "no-consent.sqlite3")
    with pytest.raises(GeminiError):
        generate_and_save(store, CONTEXT, provider)
    assert sdk.constructors == [] and store.batches() == []


@pytest.mark.parametrize("missing_check", range(3))
def test_ui_requires_three_checks_before_reading_any_key(tmp_path, monkeypatch, sdk, missing_check):
    monkeypatch.setenv("MAKASE_DB_PATH", str(tmp_path / "ui-no-consent.sqlite3"))

    def forbidden_read():
        pytest.fail("API keys/secrets must not be read during unapproved UI use")

    monkeypatch.setattr(gemini_ui, "read_api_key", forbidden_read)
    at = AppTest.from_file(str(APP), default_timeout=20).run()
    at.sidebar.radio[0].set_value("AI投稿テーマ企画").run()
    next(r for r in at.radio if r.label == "生成モード").set_value(gemini_ui.GEMINI_MODE).run()
    assert not at.exception
    model = next(s for s in at.selectbox if s.label.startswith("Geminiモデル"))
    assert model.value == "gemini-3.8-flash" and model.options == ["gemini-3.8-flash", MODEL] and not model.disabled
    assert len(at.checkbox) == 3  # Confirmation is required for all models; 3.8 has developer-reviewed provenance.
    assert any("別途承認" in info.value for info in at.info)
    next(b for b in at.button if b.label == "送信内容を更新して確認").click().run()
    for index, checkbox in enumerate(at.checkbox):
        if index != missing_check:
            checkbox.check()
    next(b for b in at.button if b.label == "テーマ10案を作成").click().run()
    assert not at.exception and at.error
    assert all(not checkbox.value for checkbox in at.checkbox)
    assert sdk.requests == sdk.constructors == [] and Store().batches() == []


def test_mock_only_ui_generates_ten_then_reviews_without_rereading_key(tmp_path, monkeypatch, sdk):
    monkeypatch.setenv("MAKASE_DB_PATH", str(tmp_path / "ui-approved-mock.sqlite3"))

    def mock_key_reader():
        sdk.key_reads += 1
        return KEY

    monkeypatch.setattr(gemini_ui, "read_api_key", mock_key_reader)
    at = AppTest.from_file(str(APP), default_timeout=20).run()
    at.sidebar.radio[0].set_value("AI投稿テーマ企画").run()
    next(r for r in at.radio if r.label == "生成モード").set_value(gemini_ui.GEMINI_MODE).run()
    assert sdk.key_reads == 0
    for checkbox in at.checkbox:
        checkbox.check()
    next(b for b in at.button if b.label == "テーマ10案を作成").click().run()
    assert not at.exception and len(Store().themes()) == 10
    assert sdk.key_reads == len(sdk.requests) == 1
    assert all(not checkbox.value for checkbox in at.checkbox)
    next(t for t in at.text_input if t.label == "テーマ名").set_value("修正した3.5モック企画")
    next(b for b in at.button if b.label == "修正を保存").click().run()
    next(b for b in at.button if b.label == "承認").click().run()
    [b for b in at.button if b.label == "却下"][1].click().run()
    assert not at.exception
    assert sum(t["status"] == "承認" for t in Store().themes()) == 1
    assert sum(t["status"] == "却下" for t in Store().themes()) == 1
    next(b for b in at.button if b.label == "テーマ10案を作成").click().run()
    assert not at.exception and sdk.key_reads == len(sdk.requests) == 1
    next(r for r in at.radio if r.label == "生成モード").set_value(gemini_ui.TEST_MODE).run()
    next(b for b in at.button if b.label == "テーマ10案を作成").click().run()
    assert not at.exception and len(Store().themes()) == 20 and sdk.key_reads == 1


@pytest.mark.parametrize("failure", [401, 403, 404, 429, 500, 504, "timeout", "invalid-json", "duplicate", "truncated"])
def test_new_model_failures_never_overwrite_existing_data_or_retry(tmp_path, sdk, caplog, failure):
    store = Store(tmp_path / "protected.sqlite3")
    generate_and_save(store, CONTEXT)
    theme = store.themes()[0]
    store.review(theme["id"], theme["version"], theme["title"], theme["outline"], "保存済みの承認", "承認")
    before = (store.batches(), store.themes(), store.audit(theme["id"]))
    if isinstance(failure, int):
        sdk.status = failure
    elif failure == "timeout":
        sdk.exception = httpx2.ReadTimeout(KEY)
    elif failure == "invalid-json":
        sdk.text = "```json\n" + sdk.text + "\n```"
    elif failure == "duplicate":
        data = json.loads(sdk.text)
        data["themes"][1]["title"] = data["themes"][0]["title"]
        sdk.text = json.dumps(data)
    else:
        sdk.finish = "MAX_TOKENS"
    with pytest.raises(GeminiError) as error:
        generate_and_save(store, CONTEXT, GeminiThemeGenerator(model=MODEL, api_key=KEY, consent=CONSENT))
    assert len(sdk.requests) == 1 and MODEL in str(sdk.requests[0].url)
    assert (store.batches(), store.themes(), store.audit(theme["id"])) == before
    assert KEY not in str(error.value) and KEY not in caplog.text


def test_new_model_duplicate_with_saved_theme_is_not_saved(tmp_path, sdk):
    store = Store(tmp_path / "duplicate.sqlite3")
    generate_and_save(store, CONTEXT, GeminiThemeGenerator(model=MODEL, api_key=KEY, consent=CONSENT))
    before = (store.batches(), store.themes())
    provider = GeminiThemeGenerator(model=MODEL, api_key=KEY, consent=CONSENT, past_titles=store.theme_titles())
    with pytest.raises(GeminiError, match="重複"):
        generate_and_save(store, CONTEXT, provider)
    assert (store.batches(), store.themes()) == before and len(sdk.requests) == 2
