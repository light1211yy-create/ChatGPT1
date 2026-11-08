"""All tests use MockTransport; no Google API calls or real keys."""
from dataclasses import asdict
from datetime import date
import json
import logging
from types import SimpleNamespace

from google import genai
from google.genai import types
import httpx2
import pytest

from studio.db import Store
from studio.gemini import (AI_LABEL, OFFICIAL_ENDPOINT, GeminiConsent, GeminiError,
                           GeminiThemeGenerator, build_payload, parse_themes)
from studio.generator import OfflineThemeGenerator, PlanningContext, ThemeDraft
from studio.planning import generate_and_save

CONTEXT = PlanningContext(date(2026, 11, 8), "おでかけ", "写真2枚、予算は本人が確認")
CONSENT = GeminiConsent(True, True, True)
TEST_KEY = "dummy-key-for-mock-only"
# Historical model IDs are used only with the synthetic review fixture below.
MODEL_CANDIDATES = ("gemini-2.5-flash-lite", "gemini-2.5-flash")


def output_json(prefix="Gemini企画"):
    return json.dumps({"themes": [dict(title=f"{prefix}{i}：秋のホテル・レストラン特集", category="おでかけ" if i % 2 else "グルメ",
        score=80+i, reason="季節に基づく提案。価格や施設は公式情報で要確認。", outline="写真1枚目で特徴 → 写真2枚目で比較 → 保存案内") for i in range(10)]}, ensure_ascii=False)


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "gemini.sqlite3")


@pytest.fixture
def transport(monkeypatch, mock_reviewed_models):
    real_client = genai.Client
    state = SimpleNamespace(calls=[], constructor_calls=[], status=200, text=output_json(), finish="STOP", exception=None)
    def handler(request):
        state.calls.append(request)
        if state.exception:
            raise state.exception
        if state.status != 200:
            return httpx2.Response(state.status, json={"error": {"code": state.status, "message": TEST_KEY + " private error", "status": "ERROR"}})
        return httpx2.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": state.text}]},
            "finishReason": state.finish}], "modelVersion": "gemini-2.5-flash-lite-001"})
    def client(**kwargs):
        state.constructor_calls.append(kwargs)
        kwargs["http_options"].client_args = {"transport": httpx2.MockTransport(handler)}
        return real_client(**kwargs)
    monkeypatch.setattr(genai, "Client", client)
    return state


def provider(**kwargs):
    values = {"api_key": TEST_KEY, "consent": CONSENT}
    values.update(kwargs)
    return GeminiThemeGenerator(**values)


def test_official_sdk_structured_output_single_call_metadata_and_persistence(store, transport, monkeypatch):
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("GOOGLE_GEMINI_BASE_URL", "https://must-not-be-used.invalid")
    batch_id = generate_and_save(store, CONTEXT, provider())
    assert len(transport.calls) == 1
    request = transport.calls[0]
    assert request.url.host == "generativelanguage.googleapis.com"
    assert "gemini-2.5-flash-lite:generateContent" in str(request.url)
    assert "key=" not in str(request.url) and request.headers["x-goog-api-key"] == TEST_KEY
    body = json.loads(request.content)
    cfg = body["generationConfig"]
    assert cfg["responseMimeType"] == "application/json"
    assert cfg["responseJsonSchema"]["properties"]["themes"]["minItems"] == 10
    assert body["tools"] == []
    # Protobuf JSON accepts the original snake_case or JSON camelCase name;
    # google-genai 3.0.0 serializes this nested object with snake_case.
    assert cfg["thinkingConfig"] in ({"thinkingBudget": 0}, {"thinking_budget": 0})
    constructor = transport.constructor_calls[0]
    assert constructor["vertexai"] is False and constructor["enterprise"] is False
    options = constructor["http_options"]
    assert options.base_url == OFFICIAL_ENDPOINT and options.timeout == 30000 and options.retry_options.attempts == 1
    reopened = Store(store.path)
    assert len(reopened.themes(batch_id)) == 10
    batch = reopened.batches()[0]
    assert "gemini-2.5-flash-lite-001" in batch["provider"] and batch["created_at"].endswith("+09:00")
    assert all(t["reason"].startswith(AI_LABEL) for t in reopened.themes(batch_id))
    assert TEST_KEY not in json.dumps(batch)


@pytest.mark.parametrize("model", MODEL_CANDIDATES)
def test_only_explicit_candidate_models_requested(store, transport, model):
    generate_and_save(store, CONTEXT, provider(model=model))
    assert len(transport.calls) == 1 and f"{model}:generateContent" in str(transport.calls[0].url)


@pytest.mark.parametrize("consent", [GeminiConsent(), GeminiConsent(False, True, True), GeminiConsent(True, False, True),
                                    GeminiConsent(True, True, False), GeminiConsent("yes", True, True)])
def test_consent_missing_never_constructs_client_or_saves(store, transport, consent):
    with pytest.raises(GeminiError):
        generate_and_save(store, CONTEXT, provider(consent=consent))
    assert transport.constructor_calls == transport.calls == []
    assert store.batches() == store.themes() == []


@pytest.mark.parametrize("key", ["", " ", None])
def test_missing_key_stops_safely_without_client(store, transport, monkeypatch, key):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "must-not-be-used")
    with pytest.raises(GeminiError, match="未設定"):
        generate_and_save(store, CONTEXT, provider(api_key=key))
    assert transport.constructor_calls == [] and store.batches() == []


@pytest.mark.parametrize("model", ["gemini-pro", "gemini-2.5-pro", "gemini-3-flash", "https://other.invalid/model"])
def test_other_models_rejected_before_network(transport, model):
    with pytest.raises(GeminiError, match="対象外"):
        provider(model=model)
    assert transport.constructor_calls == []


@pytest.mark.parametrize("status,message", [(400,"エラー"), (401,"認証"), (403,"認証"), (404,"エラー"), (429,"利用枠不足"), (500,"エラー"), (504,"タイムアウト")])
def test_api_errors_one_attempt_no_partial_save_or_secret_logging(store, transport, caplog, status, message):
    generate_and_save(store, CONTEXT)  # preserve a pre-existing test batch
    before = (store.batches(), store.themes())
    transport.status = status
    with caplog.at_level(logging.DEBUG), pytest.raises(GeminiError, match=message) as error:
        generate_and_save(store, CONTEXT, provider())
    assert len(transport.calls) == 1  # including 429/500: no retry or fallback
    assert (store.batches(), store.themes()) == before
    assert TEST_KEY not in str(error.value) and TEST_KEY not in caplog.text


@pytest.mark.parametrize("exception", [httpx2.ReadTimeout(TEST_KEY), httpx2.ConnectTimeout(TEST_KEY), TimeoutError(TEST_KEY), RuntimeError(TEST_KEY)])
def test_timeouts_and_unexpected_failures_are_sanitized(store, transport, exception):
    transport.exception = exception
    with pytest.raises(GeminiError) as error:
        generate_and_save(store, CONTEXT, provider())
    assert len(transport.calls) == 1 and store.batches() == []
    assert TEST_KEY not in str(error.value)


@pytest.mark.parametrize("kind", ["not-json", "deep-nesting", "nine", "eleven", "duplicate", "normalized-duplicate", "bool-score", "missing", "extra", "empty-reason", "category", "duplicate-key"])
def test_invalid_response_is_not_saved(store, transport, kind):
    data = json.loads(output_json())
    rows = data["themes"]
    if kind == "nine": rows.pop()
    if kind == "eleven": rows.append(dict(rows[0], title="追加"))
    if kind == "duplicate": rows[1]["title"] = rows[0]["title"]
    if kind == "normalized-duplicate": rows[1]["title"] = "  " + rows[0]["title"] + "　"
    if kind == "bool-score": rows[0]["score"] = True
    if kind == "missing": rows[0].pop("outline")
    if kind == "extra": rows[0]["extra"] = "unexpected"
    if kind == "empty-reason": rows[0]["reason"] = " "
    if kind == "category": rows[0]["category"] = "暮らし"
    raw = json.dumps(data)
    if kind == "not-json": raw = "```json\n" + raw + "\n```"
    if kind == "deep-nesting": raw = "[" * 2000 + "0" + "]" * 2000
    if kind == "duplicate-key": raw = '{"themes":[],"themes":' + json.dumps(rows) + '}'
    transport.text = raw
    with pytest.raises(GeminiError):
        generate_and_save(store, CONTEXT, provider())
    assert store.batches() == store.themes() == []


@pytest.mark.parametrize("finish", ["MAX_TOKENS", "SAFETY", "RECITATION"])
def test_incomplete_or_blocked_output_is_not_saved(store, transport, finish):
    transport.finish = finish
    with pytest.raises(GeminiError, match="中断"):
        generate_and_save(store, CONTEXT, provider())
    assert store.batches() == []


def test_payload_is_aggregate_only_and_uses_makase_profile():
    history = [{"category":"グルメ", "views":1000, "likes":50, "saves":20, "title":"PRIVATE_POST_TITLE", "id":999,
                "note":"PRIVATE_RIGHTS_NOTE", "posted_on":"PRIVATE_DATE"}]
    payload = build_payload(CONTEXT, history, ["以前のホテル特集"])
    text = json.dumps(payload, ensure_ascii=False)
    assert all(s not in text for s in ("PRIVATE_POST_TITLE", "PRIVATE_RIGHTS_NOTE", "PRIVATE_DATE", '"id"'))
    assert payload["performance_summary"] == [{"category":"グルメ", "posts":1, "views":1000, "likes":50, "saves":20}]
    assert payload["audience"]["women_percent"] == 55 and payload["audience"]["men_percent"] == 45
    assert payload["season"] == "秋" and payload["target_date"] == "2026-11-08"
    assert payload["recent_theme_titles"] == ["以前のホテル特集"] and not payload["latest_web_verified"]


@pytest.mark.parametrize("brief", ["連絡先person@example.com", "API_KEY=not-for-upload", "090-1234-5678", "AIza" + "a"*32])
def test_sensitive_input_rejected_before_sdk_client(store, transport, brief):
    context = PlanningContext(CONTEXT.target_date, "おでかけ", brief)
    with pytest.raises(GeminiError, match="秘密情報や個人情報"):
        generate_and_save(store, context, provider())
    assert transport.constructor_calls == [] and store.batches() == []


def test_all_past_titles_local_duplicate_check_even_outside_sent_300(store, transport):
    past = [f"古いテーマ{i}" for i in range(300)] + [json.loads(output_json())["themes"][0]["title"]]
    with pytest.raises(GeminiError, match="重複"):
        generate_and_save(store, CONTEXT, provider(past_titles=past))
    assert len(build_payload(CONTEXT, [], past)["recent_theme_titles"]) == 300
    assert store.batches() == []


def test_atomic_save_rechecks_titles_created_after_prompt_snapshot(store, transport):
    stale_provider = provider(past_titles=store.theme_titles())
    drafts = parse_themes(output_json(), [])
    store.save_batch(CONTEXT, "別の画面で先に生成", drafts)
    before = (store.batches(), store.themes())
    with pytest.raises(ValueError, match="重複"):
        generate_and_save(store, CONTEXT, stale_provider)
    assert (store.batches(), store.themes()) == before


def test_default_mode_never_constructs_sdk_client(store, transport):
    generate_and_save(store, CONTEXT)
    assert len(store.themes()) == 10 and transport.constructor_calls == []
