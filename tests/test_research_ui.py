from pathlib import Path

from streamlit.testing.v1 import AppTest

from studio.db import Store
from studio.generator import PlanningContext
from studio.planning import generate_and_save
from studio.research import ResearchStore, today

APP = Path(__file__).resolve().parents[1] / "app.py"


def item(app, kind, label, index=0):
    return [e for e in getattr(app, kind) if e.label == label][index]


def test_research_ui_registration_comparison_and_edit(tmp_path, monkeypatch):
    db = tmp_path / "ui.sqlite3"
    monkeypatch.setenv("MAKASE_DB_PATH", str(db))
    store = Store(db)
    generate_and_save(store, PlanningContext(today()))
    theme = store.themes()[0]
    store.review(theme["id"], 0, theme["title"], theme["outline"], "", "承認")
    at = AppTest.from_file(str(APP), default_timeout=20).run()
    at.sidebar.radio[0].set_value("施設候補リサーチ").run()
    assert not at.exception
    assert len(item(at, "selectbox", "対象テーマ").options) == 1
    for name in ("施設A", "施設B"):
        item(at, "text_input", "施設名").set_value(name)
        item(at, "text_input", "住所").set_value("東京都テスト区")
        item(at, "text_input", "施設公式URL").set_value("https://example.com/" + name)
        item(at, "button", "施設候補を登録").click().run()
        assert not at.exception
    research = ResearchStore(store)
    assert len(research.facilities(theme["id"])) == 2
    assert len(at.multiselect[0].value) == 2
    assert len(at.dataframe[0].value) == 2

    item(at, "text_input", "確認項目").set_value("営業時間")
    item(at, "text_area", "確認した情報").set_value("10〜18時")
    item(at, "text_input", "出典URL").set_value("https://example.com/hours")
    item(at, "button", "出典を保存").click().run()
    assert not at.exception
    fid = research.facilities(theme["id"])[0]["id"]
    assert research.sources(fid)[0]["fact"] == "10〜18時"

    item(at, "text_input", "写真名").set_value("外観候補")
    item(at, "text_input", "写真候補・掲載元URL").set_value("https://example.com/photo")
    item(at, "selectbox", "利用許諾状況").set_value("利用可")
    item(at, "button", "写真候補を保存").click().run()
    assert not at.exception
    assert any("許諾の根拠" in e.value for e in at.error)
    assert research.photos(fid) == []
    item(at, "text_input", "権利者").set_value("自分")
    item(at, "text_area", "許諾の根拠").set_value("自分で撮影、施設の商用撮影許可を記録")
    item(at, "text_area", "許諾された用途").set_value("商用SNS・動画編集可")
    item(at, "button", "写真候補を保存").click().run()
    assert not at.exception
    assert len(research.usable_photos(fid)) == 1
    assert at.dataframe[0].value.iloc[0]["利用可の写真数"] == 1

    item(at, "text_input", "施設名", 1).set_value("施設A修正")
    item(at, "button", "施設候補を更新").click().run()
    assert not at.exception
    assert research.facilities(theme["id"])[0]["name"] == "施設A修正"
    sid = research.sources(fid)[0]["id"]
    item(at, "selectbox", "編集する出典").set_value(sid).run()
    item(at, "text_area", "確認した情報").set_value("11〜18時")
    item(at, "button", "出典を保存").click().run()
    assert research.sources(fid)[0]["fact"] == "11〜18時"
    pid = research.photos(fid)[0]["id"]
    item(at, "selectbox", "編集する写真候補").set_value(pid).run()
    item(at, "selectbox", "利用許諾状況").set_value("利用不可")
    item(at, "button", "写真候補を保存").click().run()
    assert not at.exception
    assert research.usable_photos(fid) == []
    fresh = AppTest.from_file(str(APP), default_timeout=20).run()
    fresh.sidebar.radio[0].set_value("施設候補リサーチ").run()
    assert not fresh.exception
    assert len(fresh.dataframe[0].value) == 2

    theme = next(t for t in store.themes() if t["id"] == theme["id"])
    store.review(theme["id"], theme["version"], theme["title"], theme["outline"], "", "却下")
    fresh.run()
    assert not fresh.exception
    assert fresh.warning
    assert not fresh.button  # archived research can be viewed but cannot mutate
    assert len(fresh.dataframe[0].value) == 2


def test_research_requires_approved_theme(tmp_path, monkeypatch):
    monkeypatch.setenv("MAKASE_DB_PATH", str(tmp_path / "empty.sqlite3"))
    at = AppTest.from_file(str(APP), default_timeout=20).run()
    at.sidebar.radio[0].set_value("施設候補リサーチ").run()
    assert not at.exception
    assert any("先に" in e.value for e in at.info)
    assert not at.button
