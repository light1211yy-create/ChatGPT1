from pathlib import Path

from streamlit.testing.v1 import AppTest

from studio.db import Store

APP = Path(__file__).resolve().parents[1] / "app.py"


def button(app, label, index=0):
    return [b for b in app.button if b.label == label][index]


def input_by_label(app, kind, label):
    return next(item for item in getattr(app, kind) if item.label == label)


def test_ui_end_to_end(tmp_path, monkeypatch):
    db = tmp_path / "ui.sqlite3"
    monkeypatch.setenv("MAKASE_DB_PATH", str(db))
    at = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not at.exception
    assert any(h.value == "ダッシュボード" for h in at.header)
    assert at.metric[0].value == "0"

    at.sidebar.radio[0].set_value("過去の投稿実績").run()
    input_by_label(at, "text_input", "投稿タイトル").set_value("以前の動画")
    input_by_label(at, "number_input", "再生数").set_value(1000)
    input_by_label(at, "number_input", "いいね数").set_value(100)
    button(at, "実績を登録").click().run()
    assert not at.exception
    assert len(Store(db).performance()) == 1

    at.sidebar.radio[0].set_value("AI投稿テーマ企画").run()
    button(at, "テーマ10案を作成").click().run()
    assert not at.exception
    store = Store(db)
    assert len(store.themes()) == 10
    assert len(at.expander) == 10
    assert db.exists()
    assert all(t["reason"] and 0 <= t["score"] <= 100 for t in store.themes())
    first = at.text_input[0]
    first.set_value("画面で修正したテーマ")
    input_by_label(at, "text_area", "投稿構成").set_value("冒頭の問い → 実演 → 振り返り")
    button(at, "修正を保存").click().run()
    assert not at.exception
    edited = next(t for t in store.themes() if t["title"] == "画面で修正したテーマ")
    assert edited["status"] == "修正済み"
    assert edited["outline"] == "冒頭の問い → 実演 → 振り返り"
    assert store.audit(edited["id"])[0]["action"] == "修正済み"
    button(at, "承認").click().run()
    assert not at.exception
    assert next(t for t in store.themes() if t["id"] == edited["id"])["status"] == "承認"
    button(at, "却下", 1).click().run()
    assert not at.exception
    assert sum(t["status"] == "却下" for t in store.themes()) == 1

    at.sidebar.radio[0].set_value("投稿制作の進捗管理").run()
    input_by_label(at, "selectbox", "制作進捗").set_value("投稿済み")
    input_by_label(at, "text_area", "制作メモ").set_value("手動で投稿を確認")
    button(at, "進捗を保存").click().run()
    assert not at.exception
    assert next(t for t in store.themes() if t["id"] == edited["id"])["progress"] == "投稿済み"

    restarted = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not restarted.exception
    assert restarted.metric[0].value == "10"
    assert restarted.metric[1].value == "8"
    assert restarted.metric[3].value == "1"


def test_ui_rejects_empty_title(tmp_path, monkeypatch):
    monkeypatch.setenv("MAKASE_DB_PATH", str(tmp_path / "invalid.sqlite3"))
    at = AppTest.from_file(str(APP), default_timeout=20).run()
    at.sidebar.radio[0].set_value("AI投稿テーマ企画").run()
    button(at, "テーマ10案を作成").click().run()
    at.text_input[0].set_value(" ")
    button(at, "承認").click().run()
    assert not at.exception
    assert any("テーマ名" in err.value for err in at.error)
    assert all(t["status"] == "未承認" for t in Store().themes())
