"""Mock-only safety checks; these do NOT validate real AI inference or billing."""
from dataclasses import asdict
from datetime import date
import json
from pathlib import Path
import sys

import pytest

from scripts import codex_theme_probe as probe
from studio.generator import OfflineThemeGenerator, PlanningContext


def ready():
    return {"account_type": "chatgpt", "plan_type": "plus", "limits_plan_type": "plus",
            "rate_limits_available": True, "has_credits": False, "unlimited_credits": False,
            "zero_credit_balance": True, "primary_used_percent": 25, "secondary_used_percent": 30,
            "api_environment_present": False}


def model_json():
    themes = []
    for d in OfflineThemeGenerator().generate(PlanningContext(date(2026, 11, 4)), []):
        row = asdict(d)
        row.update(target="日本在住18〜34歳", posting_period="2026年11月", information_basis=probe.UNVERIFIED)
        themes.append(row)
    return json.dumps({"themes": themes}, ensure_ascii=False)


@pytest.mark.parametrize("change", [{"account_type": "apiKey"}, {"plan_type": "unknown"},
    {"limits_plan_type": "pro"}, {"rate_limits_available": False}, {"has_credits": True},
    {"has_credits": None}, {"unlimited_credits": True}, {"zero_credit_balance": False},
    {"primary_used_percent": 100}, {"secondary_used_percent": None},
    {"primary_used_percent": float('nan')}, {"api_environment_present": True}])
def test_uncertain_or_paid_route_never_runs_cli(tmp_path, monkeypatch, change):
    status = ready()
    status.update(change)
    def forbidden(*args, **kwargs):
        pytest.fail("Inference must not run when preflight is blocked")
    monkeypatch.setattr(probe, "run_cli", forbidden)
    output = tmp_path / "result.json"
    with pytest.raises(probe.ProbeError, match="推論を停止"):
        probe.generate_once("codex", status, True, "2026-11-04", [], 180, output)
    assert not output.exists()


def test_explicit_no_credit_confirmation_required(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "run_cli", lambda *a, **k: pytest.fail("Must not run"))
    with pytest.raises(probe.ProbeError, match="本人"):
        probe.generate_once("codex", ready(), False, "2026-11-04", [], 180, tmp_path / "result.json")


def test_status_redaction_and_unknown_values_are_not_reflected():
    secret_marker = "PRIVATE_DIAGNOSTIC_MARKER"
    account = {"result": {"account": {"type": "chatgpt", "planType": "plus", "email": secret_marker, "token": secret_marker}}}
    limits = {"result": {"rateLimits": {"planType": "plus", "primary": {"usedPercent": 10},
        "secondary": {"usedPercent": 20}, "credits": {"hasCredits": False, "unlimited": False, "balance": "0"}}}}
    safe = probe.summarize(account, limits)
    safe["api_environment_present"] = False
    assert secret_marker not in json.dumps(safe)
    assert not probe.blocking_reasons(safe, True)
    account["result"]["account"]["planType"] = secret_marker
    limits["result"]["rateLimits"]["primary"]["usedPercent"] = secret_marker
    safe = probe.summarize(account, limits)
    assert secret_marker not in json.dumps(safe)
    assert safe["plan_type"] == "unknown" and safe["primary_used_percent"] is None


def test_missing_credit_status_is_unknown_not_zero():
    safe = probe.summarize({"result": {"account": {"type": "chatgpt", "planType": "plus"}}}, {"error": {"code": -32603}})
    assert safe["zero_credit_balance"] is None
    assert safe["has_credits"] is None
    assert not safe["rate_limits_available"]


def test_generation_command_isolated_and_no_action_tools(tmp_path):
    command = probe.inference_command("codex", tmp_path, tmp_path / "schema.json", tmp_path / "final.json")
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert '--ignore-user-config' in command and '--ephemeral' in command
    assert 'forced_login_method="chatgpt"' in command and 'model_provider="openai"' in command
    assert 'mcp_servers={}' in command and 'web_search="disabled"' in command
    assert 'features.shell_tool=false' in command and 'features.hooks=false' in command
    assert not any("dangerously" in part for part in command)
    assert command[-1] == "-"  # prompt goes through stdin, not a shell command


def test_mock_generation_maps_extra_fields_without_database(tmp_path, monkeypatch):
    calls = []
    def fake(command, **kwargs):
        calls.append(command)
        assert kwargs["timeout"] == 180 and kwargs["capture"] is False
        assert all(word in kwargs["prompt"] for word in ("マカセ", "2026-11-04", "女性約55%", "男性約45%", "写真映え"))
        Path(command[command.index("--output-last-message") + 1]).write_text(model_json(), encoding="utf-8")
        return 0, ""
    monkeypatch.setattr(probe, "run_cli", fake)
    output = tmp_path / "result.json"
    result = probe.generate_once("codex", ready(), True, "2026-11-04", [], 180, output)
    assert len(calls) == 1
    assert len(result["themes"]) == len(result["theme_drafts"]) == 10
    assert "投稿時期" in result["theme_drafts"][0]["reason"]
    assert not result["latest_web_verified"] and not result["past_themes_provided"]
    assert list(tmp_path.iterdir()) == [output]  # no database/log/credential files


@pytest.mark.parametrize("kind", ["json", "nine", "duplicate", "past", "empty-reason", "unverified", "extra"])
def test_bad_output_never_saved(tmp_path, monkeypatch, kind):
    response = json.loads(model_json())
    rows = response["themes"]
    past = []
    if kind == "nine": rows.pop()
    if kind == "duplicate": rows[1]["title"] = rows[0]["title"]
    if kind == "past": past = [rows[0]["title"]]
    if kind == "empty-reason": rows[0]["reason"] = " "
    if kind == "unverified": rows[0]["information_basis"] = "最新情報を確認済み"
    if kind == "extra": rows[0]["unknown"] = "extra"
    raw = "not-json" if kind == "json" else json.dumps(response)
    def fake(command, **kwargs):
        Path(command[command.index("--output-last-message") + 1]).write_text(raw, encoding="utf-8")
        return 0, ""
    monkeypatch.setattr(probe, "run_cli", fake)
    output = tmp_path / "result.json"
    with pytest.raises(probe.ProbeError, match="不正"):
        probe.generate_once("codex", ready(), True, "2026-11-04", past, 180, output)
    assert not output.exists()


def test_cli_failure_does_not_save_or_reveal_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "run_cli", lambda *a, **k: (1, "PRIVATE_ERROR_CONTENT"))
    with pytest.raises(probe.ProbeError) as error:
        probe.generate_once("codex", ready(), True, "2026-11-04", [], 180, tmp_path / "result.json")
    assert "PRIVATE_ERROR_CONTENT" not in str(error.value)
    assert not list(tmp_path.iterdir())


def test_existing_output_and_database_never_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "run_cli", lambda *a, **k: pytest.fail("Must not run"))
    output = tmp_path / "result.json"
    output.write_text("existing content")
    with pytest.raises(probe.ProbeError, match="上書きしません"):
        probe.generate_once("codex", ready(), True, "2026-11-04", [], 180, output)
    assert output.read_text() == "existing content"
    with pytest.raises(probe.ProbeError, match="JSON"):
        probe.generate_once("codex", ready(), True, "2026-11-04", [], 180, tmp_path / "studio.sqlite3")


def test_timeout_terminates_child_without_logs():
    with pytest.raises(probe.ProbeError, match="制限時間"):
        probe.run_cli([sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.05)
