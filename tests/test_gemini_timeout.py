"""Timeout origin, one HTTP attempt and no DB writes; mock credentials only."""
from datetime import date
import json
from pathlib import Path
import socket
from types import SimpleNamespace

from google import genai
import httpx2
import pytest
from streamlit.testing.v1 import AppTest

from studio import gemini, gemini_ui
from studio.db import Store
from studio.gemini import GeminiConsent, GeminiError, GeminiThemeGenerator
from studio.generator import PlanningContext
from studio.planning import generate_and_save

KEY = "synthetic-timeout-test-key"
MODEL = "gemini-3.8-flash"
CONTEXT = PlanningContext(date(2026, 11, 9), "おでかけ", "写真映え")
CONSENT = GeminiConsent(True, True, True)


@pytest.fixture
def sdk(monkeypatch):
    real_client = genai.Client
    state = SimpleNamespace(status=200, exception=None, requests=[], constructors=[], key_reads=0)

    def handler(request):
        state.requests.append(request)
        if state.exception:
            raise state.exception
        if state.status != 200:
            return httpx2.Response(state.status, json={"error": {"code": state.status, "message": KEY + " mock diagnostic"}})
        rows = [dict(title=f"タイムアウト設定のモック企画{i}", category="おでかけ", score=80,
                     reason="季節に合わせた提案", outline="写真と比較 → 保存案内") for i in range(10)]
        return httpx2.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [
            {"text": json.dumps({"themes": rows})}]}, "finishReason": "STOP"}], "modelVersion": MODEL})

    def client(**kwargs):
        state.constructors.append(kwargs)
        kwargs["http_options"].client_args = {"transport": httpx2.MockTransport(handler)}
        return real_client(**kwargs)

    monkeypatch.setattr(genai, "Client", client)
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("Real network forbidden"))
    return state


def seed_and_snapshot(store):
    generate_and_save(store, CONTEXT)
    theme = store.themes()[0]
    store.review(theme["id"], theme["version"], theme["title"], theme["outline"], "保存済みの承認", "承認")
    return theme["id"], (store.batches(), store.themes(), store.audit(theme["id"]))


def test_120_second_request_preserves_medium_json_and_one_attempt(tmp_path, sdk):
    store = Store(tmp_path / "success.sqlite3")
    generate_and_save(store, CONTEXT, GeminiThemeGenerator(api_key=KEY, consent=CONSENT))
    options = sdk.constructors[0]["http_options"]
    assert options.timeout == 120000 and options.retry_options.attempts == 1
    assert len(sdk.requests) == 1 and f"{MODEL}:generateContent" in str(sdk.requests[0].url)
    body = json.loads(sdk.requests[0].content)
    cfg = body["generationConfig"]
    assert cfg["thinkingConfig"] in ({"thinkingLevel": "MEDIUM"}, {"thinking_level": "MEDIUM"})
    assert "candidateCount" not in cfg and "candidate_count" not in cfg
    assert cfg["responseMimeType"] == "application/json" and cfg["responseJsonSchema"]["properties"]["themes"]["minItems"] == 10
    assert len(store.themes()) == 10


@pytest.mark.parametrize("status", [408, 504])
def test_http_timeout_names_status_without_claiming_client_timeout(tmp_path, sdk, caplog, status):
    store = Store(tmp_path / "http.sqlite3")
    tid, before = seed_and_snapshot(store)
    sdk.status = status
    with pytest.raises(GeminiError) as error:
        generate_and_save(store, CONTEXT, GeminiThemeGenerator(api_key=KEY, consent=CONSENT))
    message = str(error.value)
    assert f"HTTP {status}" in message and "応答" in message and "クライアント側" not in message
    assert "保存せず" in message and "自動再試行は行いません" in message
    assert KEY not in message and KEY not in caplog.text
    assert len(sdk.requests) == 1 and (store.batches(), store.themes(), store.audit(tid)) == before


@pytest.mark.parametrize("exception_type", [httpx2.ReadTimeout, httpx2.ConnectTimeout, httpx2.WriteTimeout,
                                           httpx2.PoolTimeout, TimeoutError])
def test_client_timeout_is_distinct_sanitized_and_never_retried(tmp_path, sdk, caplog, exception_type):
    store = Store(tmp_path / "client.sqlite3")
    tid, before = seed_and_snapshot(store)
    sdk.exception = exception_type(KEY)
    with pytest.raises(GeminiError) as error:
        generate_and_save(store, CONTEXT, GeminiThemeGenerator(api_key=KEY, consent=CONSENT))
    message = str(error.value)
    assert "クライアント側" in message and "120秒" in message
    assert "HTTP 408" not in message and "HTTP 504" not in message
    assert "保存せず" in message and "自動再試行は行いません" in message
    assert KEY not in message and KEY not in caplog.text
    assert len(sdk.requests) == 1 and (store.batches(), store.themes(), store.audit(tid)) == before


@pytest.mark.parametrize("status,expected", [(401, "認証・権限"), (403, "認証・権限"),
                                            (404, "モデルの利用エラー（404）"), (429, "利用枠不足（429）"),
                                            (503, "Gemini APIでエラー")])
def test_other_statuses_keep_existing_handling_and_no_save(tmp_path, sdk, status, expected):
    store = Store(tmp_path / "preserved.sqlite3")
    tid, before = seed_and_snapshot(store)
    sdk.status = status
    with pytest.raises(GeminiError, match=expected) as error:
        generate_and_save(store, CONTEXT, GeminiThemeGenerator(api_key=KEY, consent=CONSENT))
    assert "タイムアウト" not in str(error.value) and KEY not in str(error.value)
    assert len(sdk.requests) == 1 and (store.batches(), store.themes(), store.audit(tid)) == before


@pytest.mark.parametrize("kind", ["client", "408", "504"])
def test_ui_displays_safe_origin_resets_consent_and_can_return_offline(tmp_path, monkeypatch, sdk, kind):
    monkeypatch.setenv("MAKASE_DB_PATH", str(tmp_path / "ui.sqlite3"))
    if kind == "client":
        sdk.exception = httpx2.ReadTimeout(KEY)
    else:
        sdk.status = int(kind)

    def fake_key():
        sdk.key_reads += 1
        return KEY

    monkeypatch.setattr(gemini_ui, "read_api_key", fake_key)
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20).run()
    at.sidebar.radio[0].set_value("AI投稿テーマ企画").run()
    next(r for r in at.radio if r.label == "生成モード").set_value(gemini_ui.GEMINI_MODE).run()
    assert sdk.key_reads == 0 and any("HTTPタイムアウト120秒" in c.value for c in at.caption)
    for checkbox in at.checkbox:
        checkbox.check()
    next(b for b in at.button if b.label == "テーマ10案を作成").click().run()
    expected = "クライアント側" if kind == "client" else f"HTTP {kind}"
    assert not at.exception and any(expected in e.value for e in at.error)
    assert all(KEY not in e.value for e in at.error)
    assert all(not c.value for c in at.checkbox)
    assert sdk.key_reads == len(sdk.requests) == 1 and Store().batches() == []
    next(b for b in at.button if b.label == "テーマ10案を作成").click().run()
    assert sdk.key_reads == len(sdk.requests) == 1
    next(r for r in at.radio if r.label == "生成モード").set_value(gemini_ui.TEST_MODE).run()
    next(b for b in at.button if b.label == "テーマ10案を作成").click().run()
    assert not at.exception and len(Store().themes()) == 10 and len(sdk.requests) == 1


def test_manually_selected_low_is_single_request_and_keeps_ten_themes(tmp_path, sdk):
    store = Store(tmp_path / "manual-low.sqlite3")
    provider = GeminiThemeGenerator(api_key=KEY, consent=CONSENT, thinking_level="LOW")
    batch_id = generate_and_save(store, CONTEXT, provider)
    assert len(sdk.requests) == 1
    cfg = json.loads(sdk.requests[0].content)["generationConfig"]
    assert cfg["thinkingConfig"] in ({"thinkingLevel": "LOW"}, {"thinking_level": "LOW"})
    assert cfg["responseJsonSchema"]["properties"]["themes"]["minItems"] == 10
    assert sdk.constructors[0]["http_options"].retry_options.attempts == 1
    assert len(store.themes(batch_id)) == 10
    assert "Thinking LOW" in store.batches()[0]["provider"]


@pytest.mark.parametrize("model,level", [
    ("gemini-3.8-flash", "MINIMAL"),
    ("gemini-3.8-flash", "HIGH"),
    ("gemini-3.5-flash-lite", "LOW"),
    ("gemini-3.8-flash", ""),
])
def test_unapproved_thinking_level_stops_before_sdk(tmp_path, sdk, model, level):
    store = Store(tmp_path / "invalid-thinking.sqlite3")
    with pytest.raises(GeminiError, match="思考レベル"):
        GeminiThemeGenerator(model=model, thinking_level=level, api_key=KEY, consent=CONSENT)
    assert store.batches() == [] and sdk.requests == [] and sdk.constructors == []


def test_ui_manual_low_requires_fresh_consent_and_does_not_read_key_on_selection(tmp_path, monkeypatch, sdk):
    monkeypatch.setenv("MAKASE_DB_PATH", str(tmp_path / "ui-low.sqlite3"))
    def fake_key():
        sdk.key_reads += 1
        return KEY
    monkeypatch.setattr(gemini_ui, "read_api_key", fake_key)
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20).run()
    at.sidebar.radio[0].set_value("AI投稿テーマ企画").run()
    next(r for r in at.radio if r.label == "生成モード").set_value(gemini_ui.GEMINI_MODE).run()
    level = next(s for s in at.selectbox if s.label.startswith("Gemini 3.8 Flashの思考レベル"))
    assert level.value == "MEDIUM" and sdk.key_reads == 0
    for checkbox in at.checkbox:
        checkbox.check()
    level.set_value("LOW").run()
    assert sdk.key_reads == 0 and sdk.requests == []
    assert all(not c.value for c in at.checkbox)
    for checkbox in at.checkbox:
        checkbox.check()
    next(b for b in at.button if b.label == "テーマ10案を作成").click().run()
    assert sdk.key_reads == len(sdk.requests) == 1
    config = json.loads(sdk.requests[0].content)["generationConfig"]
    assert config["thinkingConfig"] in ({"thinkingLevel": "LOW"}, {"thinking_level": "LOW"})
    assert len(Store().themes()) == 10
