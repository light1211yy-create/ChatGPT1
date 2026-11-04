from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import studio.db as database
from studio.db import Store
from studio.generator import PlanningContext
from studio.planning import generate_and_save
from studio.research import ResearchStore, today

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("MAKASE_DB_PATH", str(tmp_path / "fixes.sqlite3"))
    return Store()


@pytest.mark.parametrize("value", [None, "2026-11-04", datetime(2026, 1, 1), 42, True])
def test_invalid_performance_date_type_never_saved(store, value):
    with pytest.raises(ValueError, match="投稿日.*日付"):
        store.add_performance("投稿", "暮らし", value, 100, 1, 1)
    assert store.performance() == []


@pytest.mark.parametrize("position", [0, 1, 2])
@pytest.mark.parametrize("value", [True, False, -1, 1.5, "1", None])
def test_all_performance_counts_require_exact_nonnegative_int(store, position, value):
    counts = [100, 10, 5]
    counts[position] = value
    with pytest.raises(ValueError, match="0以上の整数"):
        store.add_performance("投稿", "暮らし", database.today_jst(), *counts)
    assert store.performance() == []


@pytest.mark.parametrize("counts", [(0, 0, 0), (1, 0, 1), (100, 100, 100)])
def test_valid_counts_and_past_date_persist(store, counts):
    posted = database.today_jst() - timedelta(days=1)
    store.add_performance("過去投稿", "暮らし", posted, *counts)
    saved = Store(store.path).performance()[0]
    assert (saved["views"], saved["likes"], saved["saves"]) == counts
    assert saved["posted_on"] == posted.isoformat()


def test_performance_boundary_is_japan_date_not_utc_date(store, monkeypatch):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 4, 15, 30, tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr(database, "datetime", FrozenDatetime)
    assert database.today_jst() == date(2026, 11, 5)
    store.add_performance("日本時間の今日", "暮らし", date(2026, 11, 5), 100, 10, 1)
    with pytest.raises(ValueError, match="今日以前"):
        store.add_performance("日本時間の未来", "暮らし", date(2026, 11, 6), 100, 10, 1)
    assert len(store.performance()) == 1


def element(at, kind, label, index=0):
    return [e for e in getattr(at, kind) if e.label == label][index]


def prepare(store):
    generate_and_save(store, PlanningContext(today()))
    t = sorted(store.themes(), key=lambda x: (-x["score"], x["id"]))[0]
    store.review(t["id"], t["version"], t["title"], t["outline"], "", "承認")
    research = ResearchStore(store)
    fid = research.save_facility(t["id"], name="施設", address="住所", official_url="https://example.com",
                                 summary="説明", price_note="条件", checked_on=today())
    sid = research.save_source(fid, label="営業時間", fact="10時", source_url="https://example.com/hours", checked_on=today())
    pid = research.save_photo(fid, label="外観", photo_url="https://example.com/photo")
    return t["id"], research, fid, sid, pid


def theme(store, identifier):
    return next(t for t in store.themes() if t["id"] == identifier)


def open_page(at, kind, sid, pid):
    page = {"review": "AI投稿テーマ企画", "progress": "投稿制作の進捗管理"}.get(kind, "施設候補リサーチ")
    at.sidebar.radio[0].set_value(page).run()
    if kind == "source": element(at, "selectbox", "編集する出典").set_value(sid).run()
    if kind == "photo": element(at, "selectbox", "編集する写真候補").set_value(pid).run()
    assert not at.exception


@pytest.mark.parametrize("kind", ["review", "progress", "facility", "source", "photo"])
def test_all_editors_preserve_draft_compare_reload_and_save(store, kind):
    tid, research, fid, sid, pid = prepare(store)
    at = AppTest.from_file(str(APP), default_timeout=20).run()
    open_page(at, kind, sid, pid)
    widget_type, label, index, submit = {
        "review": ("text_input", "テーマ名", 0, "修正を保存"),
        "progress": ("text_area", "制作メモ", 0, "進捗を保存"),
        "facility": ("text_input", "施設名", 1, "施設候補を更新"),
        "source": ("text_area", "確認した情報", 0, "出典を保存"),
        "photo": ("text_area", "写真メモ", 0, "写真候補を保存"),
    }[kind]
    draft = "自分の保存前の編集"
    latest = "別の画面で保存済み"
    element(at, widget_type, label, index).set_value(draft)
    if kind == "review":
        t = theme(store, tid)
        store.review(tid, t["version"], latest, t["outline"], "", "承認")
        def saved_value(): return theme(store, tid)["title"]
    elif kind == "progress":
        t = theme(store, tid)
        store.set_progress(tid, t["version"], "素材準備", latest)
        def saved_value(): return theme(store, tid)["note"]
    elif kind == "facility":
        research.save_facility(tid, name=latest, address="住所", official_url="https://example.com", summary="説明",
                               price_note="条件", checked_on=today(), facility_id=fid, version=0)
        def saved_value(): return research.facilities(tid)[0]["name"]
    elif kind == "source":
        research.save_source(fid, label="営業時間", fact=latest, source_url="https://example.com/hours", checked_on=today(), source_id=sid, version=0)
        def saved_value(): return research.sources(fid)[0]["fact"]
    else:
        research.save_photo(fid, label="外観", photo_url="https://example.com/photo", notes=latest, photo_id=pid, version=0)
        def saved_value(): return research.photos(fid)[0]["notes"]
    element(at, "button", submit).click().run()
    assert not at.exception and at.warning and at.error and not at.success
    assert element(at, widget_type, label, index).value == draft
    assert saved_value() == latest
    element(at, "button", "最新データを再読み込みして比較（編集を保持）").click().run()
    assert not at.exception
    comparison = next(frame.value for frame in at.dataframe if "編集中の内容" in frame.value.columns)
    assert draft in comparison["編集中の内容"].tolist()
    assert latest in comparison["最新の保存値"].tolist()
    assert element(at, widget_type, label, index).value == draft
    # Merely comparing must not silently rebase the old edit for another save.
    element(at, "button", submit).click().run()
    assert at.error and saved_value() == latest
    at.sidebar.radio[0].set_value("ダッシュボード").run()
    open_page(at, kind, sid, pid)
    assert element(at, widget_type, label, index).value == draft
    element(at, "button", "編集内容を破棄して最新データを読み込む").click().run()
    assert not at.exception and not at.warning
    assert element(at, widget_type, label, index).value == latest
    element(at, widget_type, label, index).set_value("比較後に本人が編集")
    element(at, "button", submit).click().run()
    assert not at.exception and at.success
    assert saved_value() == "比較後に本人が編集"


def test_actual_two_theme_ui_sessions_conflict_without_overwrite(store):
    prepare(store)
    a = AppTest.from_file(str(APP), default_timeout=20).run()
    b = AppTest.from_file(str(APP), default_timeout=20).run()
    a.sidebar.radio[0].set_value("AI投稿テーマ企画").run()
    b.sidebar.radio[0].set_value("AI投稿テーマ企画").run()
    a.text_input[0].set_value("画面Aの編集")
    b.text_input[0].set_value("画面Bの保存")
    element(b, "button", "修正を保存").click().run()
    assert b.success
    element(a, "button", "承認").click().run()
    assert not a.exception and a.error and a.warning and not a.success
    assert a.text_input[0].value == "画面Aの編集"
    assert any(t["title"] == "画面Bの保存" for t in store.themes())
    assert not any(t["title"] == "画面Aの編集" for t in store.themes())


@pytest.mark.parametrize("kind", ["progress", "source", "photo"])
def test_revoke_approval_preserves_pending_edit_until_reapproval(store, kind):
    tid, research, fid, sid, pid = prepare(store)
    at = AppTest.from_file(str(APP), default_timeout=20).run()
    open_page(at, kind, sid, pid)
    widget_type, label, submit = {"progress": ("text_area", "制作メモ", "進捗を保存"),
        "source": ("text_area", "確認した情報", "出典を保存"),
        "photo": ("text_area", "写真メモ", "写真候補を保存")}[kind]
    element(at, widget_type, label).set_value("保持する編集内容")
    t = theme(store, tid)
    store.review(tid, t["version"], t["title"], t["outline"], "", "却下")
    before = (store.themes(), research.sources(fid), research.photos(fid))
    element(at, "button", submit).click().run()
    assert not at.exception and at.warning and not at.success
    assert (store.themes(), research.sources(fid), research.photos(fid)) == before
    t = theme(store, tid)
    store.review(tid, t["version"], t["title"], t["outline"], "", "承認")
    open_page(at, kind, sid, pid)
    assert element(at, widget_type, label).value == "保持する編集内容"
