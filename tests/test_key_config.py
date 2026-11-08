"""Credentials are synthetic; all files, databases and transports are local tests."""
import codecs
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys

from google import genai
import httpx2
import pytest
from streamlit.testing.v1 import AppTest

from studio import key_config
from studio.db import Store
from studio.gemini import GeminiConsent, GeminiError, GeminiThemeGenerator, build_payload
from studio.gemini_models import model_profile
from studio.gemini_ui import GEMINI_MODE, TEST_MODE, read_api_key
from studio.generator import PlanningContext
from studio.planning import generate_and_save
from datetime import date

AQ = "AQ.synthetic_local_test.segment_not_a_real_credential"
AIZA = "AIza" + "synthetic_local_test_not_a_real_credential"
ROOT = Path(__file__).resolve().parents[1]
CONTEXT = PlanningContext(date(2026, 11, 9), "おでかけ", "写真映え")


@pytest.fixture(autouse=True)
def fake_environment(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("Real network forbidden"))


def write_config(root, text, encoding="utf-8"):
    path = root / ".streamlit" / "secrets.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)
    return path


@pytest.mark.parametrize("key", [AQ, AIZA, "AQ.x", "opaque-synthetic-credential"])
def test_prefix_and_length_do_not_restrict_file_keys(tmp_path, key):
    write_config(tmp_path, "GEMINI_API_KEY = " + json.dumps(key) + "\n")
    assert read_api_key() == key


@pytest.mark.parametrize("key", [AQ, AIZA, "  AQ.synthetic_env_token  "])
def test_environment_is_used_when_project_file_is_absent(monkeypatch, key):
    monkeypatch.setenv("GEMINI_API_KEY", key)
    assert read_api_key() == key.strip()
    assert key_config.configuration_status()["使用される設定元"] == "環境変数GEMINI_API_KEY"


@pytest.mark.parametrize("env", [None, "", "  \t ", "obsolete-environment-dummy"])
def test_project_file_wins_over_missing_empty_whitespace_or_old_env(tmp_path, monkeypatch, env):
    write_config(tmp_path, "GEMINI_API_KEY = " + json.dumps(AQ))
    if env is not None:
        monkeypatch.setenv("GEMINI_API_KEY", env)
    assert read_api_key() == AQ
    assert key_config.configuration_status()["使用される設定元"] == "プロジェクトの.streamlit/secrets.toml"


def test_valid_project_file_does_not_read_unused_environment_key(tmp_path, monkeypatch):
    write_config(tmp_path, "GEMINI_API_KEY = " + json.dumps(AQ))
    original = key_config.os.environ.get

    def guard(name, *args):
        if name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            pytest.fail("Project file takes priority; unused key must not be read")
        return original(name, *args)

    monkeypatch.setattr(key_config.os.environ, "get", guard)
    assert read_api_key() == AQ


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_or_blank_environment_without_file_is_clear_error(monkeypatch, value):
    if value is not None:
        monkeypatch.setenv("GEMINI_API_KEY", value)
    with pytest.raises(GeminiError, match="未設定"):
        read_api_key()


@pytest.mark.parametrize("text,code", [
    ('GEMINI_API_KEY = ""', "blank"), ('GEMINI_API_KEY = "   "', "blank"),
    ('GEMINI_API_KEY = true', "type"), ('GEMINI_API_KEY = 123', "type"),
    ('GEMINI_API_KEY = ["dummy"]', "type"), ('GEMINI_API_KEY = {value="dummy"}', "type"),
    ('[gemini]\nGEMINI_API_KEY = "dummy"', "missing_key"),
    ('gemini_api_key = "dummy"', "missing_key"),
    ('GEMINI_API_KEY = "' + AQ, "toml"), ('GEMINI_API_KEY = ' + AQ, "toml"),
    ('GEMINI_API_KEY = "AQ.first\\nAQ.second"', "control"),
])
def test_invalid_project_settings_never_fall_back_or_disclose_contents(tmp_path, monkeypatch, caplog, text, code):
    write_config(tmp_path, text)
    monkeypatch.setenv("GEMINI_API_KEY", "unused-environment-dummy")
    with pytest.raises(key_config.KeyConfigError) as error:
        read_api_key()
    assert error.value.code == code
    assert AQ not in str(error.value) and AQ not in caplog.text
    status = key_config.configuration_status()
    assert status["使用される設定元"] == "なし（ファイル設定エラーで停止）"
    assert AQ not in json.dumps(status)


def test_windows_utf8_bom_crlf_and_single_quoted_strings(tmp_path):
    path = write_config(tmp_path, "")
    path.write_bytes(codecs.BOM_UTF8 + ("GEMINI_API_KEY = '" + AQ + "'\r\n").encode("utf-8"))
    assert read_api_key() == AQ


def test_non_utf8_file_has_sanitized_error(tmp_path):
    path = write_config(tmp_path, "")
    path.write_bytes(b"\xff\xfe\x80\x81")
    with pytest.raises(key_config.KeyConfigError, match="UTF-8") as error:
        read_api_key()
    assert error.value.code == "toml"


def test_read_permission_error_is_not_misreported_as_missing(tmp_path, monkeypatch):
    path = write_config(tmp_path, 'GEMINI_API_KEY = "dummy"')
    original = Path.read_text

    def unreadable(self, *args, **kwargs):
        if self == path:
            raise PermissionError(AQ)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable)
    with pytest.raises(key_config.KeyConfigError, match="読み取れません") as error:
        read_api_key()
    assert AQ not in str(error.value)


def test_project_path_is_independent_of_windows_launcher_working_directory(tmp_path, monkeypatch):
    write_config(tmp_path, "GEMINI_API_KEY = " + json.dumps(AQ))
    other = tmp_path / "another-launch-directory"
    write_config(other, 'GEMINI_API_KEY = "other-project-dummy"')
    monkeypatch.chdir(other)
    assert read_api_key() == AQ
    assert key_config.project_secrets_path() == tmp_path / ".streamlit" / "secrets.toml"


def test_file_updates_are_not_hidden_by_streamlit_secret_cache(tmp_path, monkeypatch):
    import streamlit as st
    monkeypatch.setattr(type(st.secrets), "get", lambda *a, **k: pytest.fail("Streamlit cache must not be consulted"))
    path = write_config(tmp_path, "GEMINI_API_KEY = " + json.dumps(AQ))
    assert read_api_key() == AQ
    path.write_text("GEMINI_API_KEY = " + json.dumps(AIZA), encoding="utf-8")
    assert read_api_key() == AIZA


def test_hidden_txt_extension_is_reported_without_reading_it(tmp_path):
    path = tmp_path / ".streamlit" / "secrets.toml.txt"
    path.parent.mkdir()
    path.write_text(AQ, encoding="utf-8")
    status = key_config.configuration_status()
    assert status[".streamlit/secrets.toml.txt"].startswith("あり")
    assert status["使用される設定元"] == "なし"
    assert AQ not in json.dumps(status)


def test_status_command_prints_only_states_and_imports_no_api_or_ui(tmp_path):
    # Execute the real module entry point from a disposable fake project.
    module = tmp_path / "studio" / "key_config.py"
    module.parent.mkdir()
    module.write_text((ROOT / "studio/key_config.py").read_text(), encoding="utf-8")
    (tmp_path / "app.py").write_text("# diagnostic fixture\n", encoding="utf-8")
    write_config(tmp_path, "GEMINI_API_KEY = " + json.dumps(AQ))
    code = """
import importlib.abc,runpy,sys
class NoClients(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname in ('google','streamlit','sqlite3'):
   raise AssertionError('No API/UI/DB imports in diagnostics')
sys.meta_path.insert(0,NoClients())
runpy.run_path(sys.argv[1],run_name='__main__')
"""
    result = subprocess.run([sys.executable, "-c", code, str(module)], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stderr
    status = json.loads(result.stdout)
    assert status["app.py"] == "あり" and status["API通信"] == "行いません"
    assert status["使用される設定元"] == "プロジェクトの.streamlit/secrets.toml"
    assert AQ not in result.stdout and "AQ.synthetic" not in result.stdout
    assert hashlib.sha256(AQ.encode()).hexdigest() not in result.stdout
    assert str(tmp_path) not in result.stdout


def test_diagnostic_metadata_errors_are_state_only(tmp_path, monkeypatch, capsys):
    write_config(tmp_path, "GEMINI_API_KEY = " + json.dumps(AQ))
    monkeypatch.setattr(Path, "is_file", lambda *a: (_ for _ in ()).throw(PermissionError(AQ)))
    monkeypatch.setattr(Path, "exists", lambda *a: (_ for _ in ()).throw(PermissionError(AQ)))
    key_config.print_diagnostics()
    output = capsys.readouterr().out
    status = json.loads(output)
    assert status["app.py"] == status[".streamlit/secrets.toml.txt"] == "確認不可"
    assert AQ not in output


@pytest.mark.parametrize("key", [AQ, AIZA])
@pytest.mark.parametrize("source", ["file", "environment"])
@pytest.mark.parametrize("model,level", [("gemini-3.8-flash", "MEDIUM"), ("gemini-3.5-flash-lite", "MINIMAL")])
def test_dummy_key_pipeline_through_sdk_preserves_models_and_never_logs_key(tmp_path, monkeypatch, caplog, key, source, model, level):
    if source == "file":
        write_config(tmp_path, "GEMINI_API_KEY = " + json.dumps(key))
        monkeypatch.setenv("GEMINI_API_KEY", "obsolete-dummy-env")
    else:
        monkeypatch.setenv("GEMINI_API_KEY", key)
    monkeypatch.setenv("GOOGLE_API_KEY", "unused-google-dummy-env")
    real_client = genai.Client
    requests = []

    def handler(request):
        requests.append(request)
        rows = [dict(title=f"設定読込テスト{i}", category="おでかけ", score=80, reason="企画の提案", outline="写真と比較") for i in range(10)]
        return httpx2.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps({"themes": rows})}]}, "finishReason": "STOP"}], "modelVersion": model})

    def client(**kwargs):
        kwargs["http_options"].client_args = {"transport": httpx2.MockTransport(handler)}
        return real_client(**kwargs)

    monkeypatch.setattr(genai, "Client", client)
    store = Store(tmp_path / "key-pipeline.sqlite3")
    generate_and_save(store, CONTEXT, GeminiThemeGenerator(model=model, api_key=read_api_key(), consent=GeminiConsent(True, True, True)))
    assert len(requests) == 1 and requests[0].headers["x-goog-api-key"] == key
    assert key not in str(requests[0].url) and key not in requests[0].content.decode()
    config = json.loads(requests[0].content)["generationConfig"]
    assert config["thinkingConfig"] in ({"thinking_level": level}, {"thinkingLevel": level})
    assert "candidateCount" not in config and "candidate_count" not in config
    assert model_profile().model_id == "gemini-3.8-flash"
    assert len(store.themes()) == 10 and key not in json.dumps(store.batches()) and key not in caplog.text


@pytest.mark.parametrize("field", ["brief", "history"])
def test_aq_credentials_in_planning_data_are_rejected_before_sdk(tmp_path, monkeypatch, field):
    monkeypatch.setattr(genai, "Client", lambda **k: pytest.fail("No SDK before sensitive-text validation"))
    context = PlanningContext(CONTEXT.target_date, CONTEXT.focus, "日本語のキー" + AQ if field == "brief" else "写真映え")
    provider = GeminiThemeGenerator(api_key=AQ, consent=GeminiConsent(True, True, True), past_titles=[AQ] if field == "history" else [])
    store = Store(tmp_path / "sensitive.sqlite3")
    with pytest.raises(GeminiError, match="秘密情報") as error:
        generate_and_save(store, context, provider)
    assert AQ not in str(error.value) and store.batches() == []


def test_ordinary_faq_text_is_not_mistaken_for_aq_credentials():
    assert build_payload(PlanningContext(CONTEXT.target_date, CONTEXT.focus, "FAQ.exampleの構成を参考にする"), [], [])


def test_unapproved_ui_never_reads_existing_dummy_secret_file(tmp_path, monkeypatch):
    write_config(tmp_path, "GEMINI_API_KEY = " + json.dumps(AQ))
    monkeypatch.setenv("MAKASE_DB_PATH", str(tmp_path / "ui.sqlite3"))
    monkeypatch.setattr(key_config, "_file_key", lambda *a: pytest.fail("No secret read before approval"))
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20).run()
    at.sidebar.radio[0].set_value("AI投稿テーマ企画").run()
    next(r for r in at.radio if r.label == "生成モード").set_value(GEMINI_MODE).run()
    next(b for b in at.button if b.label == "送信内容を更新して確認").click().run()
    next(b for b in at.button if b.label == "テーマ10案を作成").click().run()
    assert not at.exception and at.error and Store().batches() == []
    next(r for r in at.radio if r.label == "生成モード").set_value(TEST_MODE).run()
    next(b for b in at.button if b.label == "テーマ10案を作成").click().run()
    assert not at.exception and len(Store().themes()) == 10
