import json
from dataclasses import asdict
from datetime import date

import pytest

from studio.db import Store
from studio.generator import JsonThemeGenerator, OfflineThemeGenerator, PlanningContext
from studio.planning import generate_and_save


def test_model_adapter_receives_context_and_saves_valid_output(tmp_path):
    store = Store(tmp_path / "model.sqlite3")
    context = PlanningContext(date(2026, 11, 4), "グルメ", "顔出しなし")
    store.add_performance("過去の動画", "グルメ", date(2026, 10, 1), 100, 10, 5)
    def complete(prompt):
        assert all(word in prompt for word in ("2026-11-04", "紅葉", "日本在住18〜34歳", "顔出しなし", "過去の動画"))
        return json.dumps({"themes": [asdict(t) for t in OfflineThemeGenerator().generate(context, [])]}, ensure_ascii=False)
    batch_id = generate_and_save(store, context, JsonThemeGenerator(complete, "テスト用モデル"))
    assert len(store.themes(batch_id)) == 10
    assert store.batches()[0]["provider"] == "ローカルAI：テスト用モデル"


@pytest.mark.parametrize("failure", ["invalid-json", "nine", "duplicate", "bool-score", "empty-reason", "extra-key", "invalid-category"])
def test_invalid_model_output_never_saved(tmp_path, failure):
    store = Store(tmp_path / "invalid.sqlite3")
    context = PlanningContext(date(2026, 11, 4))
    drafts = [asdict(t) for t in OfflineThemeGenerator().generate(context, [])]
    if failure == "nine":
        drafts.pop()
    if failure == "duplicate":
        drafts[1]["title"] = drafts[0]["title"]
    if failure == "bool-score":
        drafts[0]["score"] = True
    if failure == "empty-reason":
        drafts[0]["reason"] = " "
    if failure == "extra-key":
        drafts[0]["extra"] = "unknown"
    if failure == "invalid-category":
        drafts[0]["category"] = "未知の分類"
    response = "not JSON" if failure == "invalid-json" else json.dumps({"themes": drafts})
    with pytest.raises(ValueError, match="AIの出力形式"):
        generate_and_save(store, context, JsonThemeGenerator(lambda prompt: response, "fake"))
    assert store.batches() == store.themes() == []


def test_model_failure_does_not_leak_details_or_save(tmp_path):
    def fail(prompt):
        raise RuntimeError("private model diagnostic")
    store = Store(tmp_path / "failed.sqlite3")
    with pytest.raises(ValueError, match="AI生成に失敗") as error:
        generate_and_save(store, PlanningContext(date(2026, 1, 1)), JsonThemeGenerator(fail, "fake"))
    assert "private model diagnostic" not in str(error.value)
    assert store.batches() == []
