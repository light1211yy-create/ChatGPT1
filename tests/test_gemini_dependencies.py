"""Missing Gemini dependencies must not prevent local app use; no API calls."""
import builtins
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest
from streamlit.testing.v1 import AppTest

from studio.db import Store
from studio.gemini_ui import GEMINI_MODE

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("missing", ["google.genai", "google.genai.types", "httpx2"])
def test_fresh_process_without_sdk_can_import_app_and_generate_offline(tmp_path, missing):
    # A separate interpreter also exercises module imports rather than cached
    # modules loaded by other tests. Block the SDK without uninstalling anything.
    script = r'''
import importlib.abc
import os
import socket
import sys
from datetime import date

class MissingDependency(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == os.environ['MAKASE_TEST_MISSING_SDK'] or fullname.startswith(os.environ['MAKASE_TEST_MISSING_SDK'] + '.'):
            raise ImportError('simulated dependency failure; do not expose diagnostic')

sys.meta_path.insert(0, MissingDependency())
def forbid_network(*args, **kwargs):
    raise AssertionError('Real network forbidden')
socket.socket.connect = forbid_network

import app
from studio.db import Store
from studio.generator import PlanningContext
from studio.gemini import GeminiConsent, GeminiError, GeminiThemeGenerator
from studio.planning import generate_and_save

store = Store()
context = PlanningContext(date(2026, 11, 8), 'おでかけ', '')
generate_and_save(store, context)
before = (store.batches(), store.themes())
assert len(before[1]) == 10
try:
    generate_and_save(store, context, GeminiThemeGenerator(api_key='mock-key-only', consent=GeminiConsent(True, True, True)))
except GeminiError as error:
    assert 'setup_windows.bat' in str(error)
    assert '無料テストモード' in str(error)
    assert 'mock-key-only' not in str(error)
    assert 'diagnostic' not in str(error)
else:
    raise AssertionError('Missing dependency must stop Gemini generation')
assert (store.batches(), store.themes()) == before
'''
    env = dict(os.environ, MAKASE_DB_PATH=str(tmp_path / "missing-sdk.sqlite3"),
               MAKASE_TEST_MISSING_SDK=missing, GEMINI_API_KEY="", GOOGLE_API_KEY="")
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_missing_sdk_ui_keeps_all_pages_and_test_mode_usable(tmp_path, monkeypatch):
    database = tmp_path / "ui.sqlite3"
    monkeypatch.setenv("MAKASE_DB_PATH", str(database))
    monkeypatch.setenv("GEMINI_API_KEY", "mock-key-only")
    real_import = builtins.__import__
    attempts = []

    def missing_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "httpx2" or name.startswith("google.genai") or (name == "google" and "genai" in (fromlist or ())):
            attempts.append(name)
            raise ImportError("mock-key-only private diagnostic")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", missing_import)
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("Real network forbidden"))
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20).run()
    assert not at.exception
    for page in ("過去の投稿実績", "施設候補リサーチ", "投稿制作の進捗管理", "AI投稿テーマ企画"):
        at.sidebar.radio[0].set_value(page).run()
        assert not at.exception
    next(b for b in at.button if b.label == "テーマ10案を作成").click().run()
    assert not at.exception and len(Store(database).themes()) == 10 and not attempts
    before = (Store(database).batches(), Store(database).themes())
    next(r for r in at.radio if r.label == "生成モード").set_value(GEMINI_MODE).run()
    assert not at.exception and not attempts
    for checkbox in at.checkbox:
        checkbox.check()
    next(b for b in at.button if b.label == "テーマ10案を作成").click().run()
    assert not at.exception and attempts == ["google"]
    assert any("setup_windows.bat" in e.value for e in at.error)
    assert all("mock-key-only" not in e.value for e in at.error)
    assert all(not c.value for c in at.checkbox)
    assert (Store(database).batches(), Store(database).themes()) == before
