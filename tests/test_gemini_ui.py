"""Streamlit tests using a fake SDK client. No external AI communication."""
import json
from pathlib import Path
from types import SimpleNamespace
import socket

from google import genai
from google.genai import types
import pytest
from streamlit.testing.v1 import AppTest

from studio.db import Store
from studio.gemini_ui import GEMINI_MODE, TEST_MODE

APP = Path(__file__).resolve().parents[1] / "app.py"


def item(at, kind, label, index=0):
    return [e for e in getattr(at, kind) if e.label == label][index]


@pytest.fixture
def ui(tmp_path, monkeypatch):
    monkeypatch.setenv("MAKASE_DB_PATH", str(tmp_path / "ui.sqlite3"))
    monkeypatch.setenv("GEMINI_API_KEY", "mock-ui-key")
    state = SimpleNamespace(calls=[], clients=0, fail=False)
    text = json.dumps({"themes":[dict(title=f"モックホテル企画{i}", category="おでかけ", score=70+i,
        reason="季節の提案、公式情報は要確認", outline="写真1 → 写真2 → 保存案内") for i in range(10)]}, ensure_ascii=False)
    def generate(**kwargs):
        state.calls.append(kwargs)
        if state.fail:
            from google.genai.errors import ClientError
            raise ClientError(429, {"error":{"message":"mock-ui-key private diagnostic"}})
        return SimpleNamespace(candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)],
                               text=text, model_version="gemini-2.5-flash-lite")
    class Client:
        def __init__(self, **kwargs):
            state.clients += 1
            self.models = SimpleNamespace(generate_content=generate)
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(genai, "Client", Client)
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("Real network forbidden in mock UI tests"))
    at = AppTest.from_file(str(APP), default_timeout=20).run()
    at.sidebar.radio[0].set_value("AI投稿テーマ企画").run()
    return at, Store(), state


def approve_request(at):
    for checkbox in at.checkbox:
        checkbox.check()


def test_default_test_mode_and_switch_do_not_call_api(ui):
    at, store, state = ui
    assert item(at, "radio", "生成モード").value == TEST_MODE
    item(at, "button", "テーマ10案を作成").click().run()
    assert not at.exception and len(store.themes()) == 10 and state.clients == 0
    item(at, "radio", "生成モード").set_value(GEMINI_MODE).run()
    assert not at.exception and state.clients == 0
    assert any("外部送信" in w.value for w in at.warning)
    assert any("無料枠は未確認" in x.value for x in at.info)
    item(at, "radio", "生成モード").set_value(TEST_MODE).run()
    assert not at.exception and state.clients == 0


def test_gemini_mode_without_confirmations_is_safe(ui):
    at, store, state = ui
    item(at, "radio", "生成モード").set_value(GEMINI_MODE).run()
    item(at, "button", "テーマ10案を作成").click().run()
    assert not at.exception and any("無料枠" in e.value for e in at.error)
    assert state.clients == 0 and store.batches() == []
    assert all(not c.value for c in at.checkbox)


def test_missing_key_is_japanese_error_without_sdk(ui, monkeypatch):
    at, store, state = ui
    monkeypatch.delenv("GEMINI_API_KEY")
    import streamlit as st
    monkeypatch.setattr(type(st.secrets), "get", lambda *a, **k: "")
    item(at, "radio", "生成モード").set_value(GEMINI_MODE).run()
    approve_request(at)
    item(at, "button", "テーマ10案を作成").click().run()
    assert not at.exception and any("未設定" in e.value for e in at.error)
    assert state.clients == 0 and store.batches() == []


def test_preview_updates_without_generation_and_key_never_shown(ui):
    at, store, state = ui
    item(at, "radio", "生成モード").set_value(GEMINI_MODE).run()
    item(at, "text_area", "企画メモ（任意）").set_value("ホテルの非日常感を重視")
    item(at, "button", "送信内容を更新して確認").click().run()
    assert not at.exception
    payload = json.loads(at.json[0].value)
    assert payload["brief"] == "ホテルの非日常感を重視"
    assert "mock-ui-key" not in at.json[0].value
    assert state.clients == 0 and store.batches() == []


def test_mock_10_themes_can_be_displayed_edited_approved_rejected(ui):
    at, store, state = ui
    item(at, "radio", "生成モード").set_value(GEMINI_MODE).run()
    approve_request(at)
    item(at, "button", "テーマ10案を作成").click().run()
    assert not at.exception and len(state.calls) == 1
    assert len(store.themes()) == len(at.expander)-1 == 10  # includes payload preview
    assert "Gemini AIモード" in store.batches()[0]["provider"]
    assert any("生成日時" in c.value for c in at.caption)
    assert all(not c.value for c in at.checkbox)  # one-use approval consumed
    item(at, "text_input", "テーマ名").set_value("修正したGemini案")
    item(at, "button", "修正を保存").click().run()
    assert not at.exception and any(t["title"] == "修正したGemini案" for t in store.themes())
    item(at, "button", "承認").click().run()
    item(at, "button", "却下", 1).click().run()
    assert not at.exception
    assert sum(t["status"] == "承認" for t in store.themes()) == 1
    assert sum(t["status"] == "却下" for t in store.themes()) == 1
    assert len(state.calls) == 1
    # A second click without new approval must not consume another API request.
    item(at, "button", "テーマ10案を作成").click().run()
    assert state.clients == 1 and len(store.batches()) == 1


def test_quota_error_does_not_save_or_retry_and_test_mode_still_works(ui):
    at, store, state = ui
    state.fail = True
    item(at, "radio", "生成モード").set_value(GEMINI_MODE).run()
    approve_request(at)
    item(at, "button", "テーマ10案を作成").click().run()
    assert not at.exception and any("429" in e.value for e in at.error)
    assert all("mock-ui-key" not in e.value for e in at.error)
    assert len(state.calls) == 1 and store.batches() == []
    assert all(not c.value for c in at.checkbox)
    item(at, "radio", "生成モード").set_value(TEST_MODE).run()
    item(at, "button", "テーマ10案を作成").click().run()
    assert not at.exception and len(store.themes()) == 10
    assert len(state.calls) == 1


def test_secret_file_key_is_used_without_copying_to_session(monkeypatch):
    from studio.gemini_ui import read_api_key
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    import streamlit as st
    monkeypatch.setattr(type(st.secrets), "get", lambda *a, **k: "mock-secret-file-key")
    assert read_api_key() == "mock-secret-file-key"
