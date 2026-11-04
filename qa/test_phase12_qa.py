"""Additional QA acceptance/reproduction tests; production code is unchanged.

Run explicitly: python -m pytest -q qa/test_phase12_qa.py
Known defects are ordinary failing tests, not xfail/disabled checks.
Every test uses a temporary database, never the user's data directory.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
import socket
import sqlite3
from threading import Barrier

import pytest
from streamlit.testing.v1 import AppTest

from studio.db import ConflictError, PROGRESS, Store
from studio.generator import CATEGORIES, EVENTS, OfflineThemeGenerator, PlanningContext
from studio.planning import generate_and_save
from studio.research import ResearchStore, effective_permission, today

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("MAKASE_DB_PATH", str(tmp_path / "qa.sqlite3"))


def seeded():
    store = Store()
    generate_and_save(store, PlanningContext(date(2026, 11, 4)))
    return store


def approve(store, theme):
    store.review(theme["id"], theme["version"], theme["title"], theme["outline"], "QA", "承認")
    return next(t for t in store.themes() if t["id"] == theme["id"])


def facility(research, theme_id, **changes):
    fields = dict(name="QA施設", address="QA住所", official_url="https://example.com/official",
                  summary="アクセス情報", price_note="2名・税込・日付で変動", checked_on=today(), notes="比較理由")
    fields.update(changes)
    return research.save_facility(theme_id, **fields)


def ui(page):
    at = AppTest.from_file(str(APP), default_timeout=20).run()
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception
    return at


def element(at, kind, label, index=0):
    return [e for e in getattr(at, kind) if e.label == label][index]


@pytest.mark.parametrize("month,season", [(1,"冬"),(2,"冬"),(3,"春"),(4,"春"),(5,"春"),(6,"夏"),
                                        (7,"夏"),(8,"夏"),(9,"秋"),(10,"秋"),(11,"秋"),(12,"冬")])
def test_all_months_and_focus_scores(month, season):
    drafts = OfflineThemeGenerator().generate(PlanningContext(date(2026, month, 4), "グルメ"), [])
    assert len(drafts) == 10
    for d in drafts:
        assert f"季節：{season}" in d.reason and EVENTS[month] in d.reason
        assert d.score == (75 if d.category == "グルメ" else 65)


def test_weighted_performance_and_cap():
    history = [{"category":"グルメ","views":100,"likes":10,"saves":10},
               {"category":"グルメ","views":900,"likes":10,"saves":0},
               {"category":"暮らし","views":100,"likes":100,"saves":100}]
    drafts = OfflineThemeGenerator().generate(PlanningContext(date(2026,11,4), "グルメ"), history)
    assert all(d.score == 78 for d in drafts if d.category == "グルメ")
    assert all(d.score == 85 for d in drafts if d.category == "暮らし")


def test_repeated_same_inputs_are_separate_batches():
    store = seeded()
    original = sorted(store.themes(), key=lambda t: t["title"])
    second = generate_and_save(store, PlanningContext(date(2026,11,4)))
    assert len(store.batches()) == 2 and len(store.themes()) == 20
    assert [t["title"] for t in original] == sorted(t["title"] for t in store.themes(second))


def test_dashboard_exact_stage_counts_and_all_page_navigation():
    store = seeded()
    themes = store.themes()
    for theme, stage in zip(themes[:7], PROGRESS):
        t = approve(store, theme)
        store.set_progress(t["id"], t["version"], stage, "QA")
    t = themes[7]
    store.review(t["id"], t["version"], t["title"], t["outline"], "", "却下")
    at = ui("ダッシュボード")
    assert [m.value for m in at.metric] == ["10", "2", "5", "1"]
    for page in ("AI投稿テーマ企画", "投稿制作の進捗管理", "過去の投稿実績", "施設候補リサーチ", "ダッシュボード"):
        at.sidebar.radio[0].set_value(page).run()
        assert not at.exception
    at.sidebar.radio[0].set_value("AI投稿テーマ企画").run()
    assert any("AIモデルには接続していません" in v.value for v in at.info)


def test_performance_reopen_and_japanese_sql_safety():
    store = Store()
    title = "日本語 '); DROP TABLE themes; --"
    store.add_performance(title, "グルメ", today(), 1000, 10, 20)
    reopened = Store(store.path)
    assert reopened.performance()[0]["title"] == title
    assert reopened.themes() == []


def test_batch_failure_rolls_back_partial_rows():
    store = seeded()
    before = (store.themes(), store.batches())
    with store.connect() as conn:
        conn.executescript("""CREATE TRIGGER fail_batch BEFORE INSERT ON themes
            WHEN NEW.batch_id > 1 AND (SELECT COUNT(*) FROM themes WHERE batch_id=NEW.batch_id) >= 3
            BEGIN SELECT RAISE(ABORT, 'QA simulated write failure'); END;""")
    with pytest.raises(sqlite3.IntegrityError):
        generate_and_save(store, PlanningContext(date(2026,11,4)))
    assert (store.themes(), store.batches()) == before
    with store.connect() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_audit_failure_rolls_back_review():
    store = seeded()
    theme = store.themes()[0]
    with store.connect() as conn:
        conn.executescript("""CREATE TRIGGER fail_audit BEFORE INSERT ON audit
            BEGIN SELECT RAISE(ABORT, 'QA simulated audit failure'); END;""")
    with pytest.raises(sqlite3.IntegrityError):
        approve(store, theme)
    assert store.themes()[0] == theme and store.audit(theme["id"]) == []


def test_true_simultaneous_review_has_one_winner():
    store = seeded()
    theme = store.themes()[0]
    barrier = Barrier(2)
    def writer(status):
        barrier.wait(timeout=5)
        try:
            store.review(theme["id"], 0, theme["title"], theme["outline"], "QA", status)
            return "saved"
        except ConflictError:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(writer, ("承認", "却下")))
    assert sorted(result) == ["conflict", "saved"]
    assert len(store.audit(theme["id"])) == 1


def test_true_simultaneous_facility_update_has_one_winner():
    store = seeded()
    t = approve(store, store.themes()[0])
    research = ResearchStore(store)
    fid = facility(research, t["id"])
    barrier = Barrier(2)
    def writer(name):
        barrier.wait(timeout=5)
        try:
            facility(research, t["id"], name=name, facility_id=fid, version=0)
            return "saved"
        except ConflictError:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(writer, ("更新A", "更新B")))
    assert sorted(result) == ["conflict", "saved"]
    assert research.facilities(t["id"])[0]["version"] == 1


@pytest.mark.parametrize("source_url", ["javascript:alert(1)", "file:///tmp/qa", "https://", "https://example.com/a b", "https://example.com:bad"])
def test_source_bad_url_rejected(source_url):
    store = seeded()
    t = approve(store, store.themes()[0])
    research = ResearchStore(store)
    fid = facility(research, t["id"])
    with pytest.raises(ValueError):
        research.save_source(fid, label="営業時間", fact="10時", source_url=source_url, checked_on=today())
    assert research.sources(fid) == []


def test_source_future_date_rollback_and_fields_reopen():
    store = seeded()
    t = approve(store, store.themes()[0])
    research = ResearchStore(store)
    fid = facility(research, t["id"])
    with pytest.raises(ValueError):
        research.save_source(fid, label="営業時間", fact="10時", source_url="https://example.com", checked_on=today()+timedelta(days=1))
    research.save_source(fid, label="営業時間", fact="10時", source_url="https://example.com", checked_on=today(), notes="確認記録")
    reopened = ResearchStore(Store(store.path))
    assert reopened.sources(fid)[0]["notes"] == "確認記録"
    assert reopened.facilities(t["id"])[0]["price_note"] == "2名・税込・日付で変動"


def test_photo_expiry_day_boundary_and_scoped_rights():
    store = seeded()
    t = approve(store, store.themes()[0])
    research = ResearchStore(store)
    fid = facility(research, t["id"])
    research.save_photo(fid, label="写真", photo_url="https://example.com/photo", owner="撮影者", permission_status="利用可",
                        evidence="許諾書参照", usage_scope="TikTokの商用投稿、トリミング可", credit="撮影者名", expires_on=today())
    p = research.photos(fid)[0]
    assert effective_permission(p, today()) == "利用可"
    assert effective_permission(p, today()+timedelta(days=1)) == "期限切れ"
    assert p["usage_scope"] == "TikTokの商用投稿、トリミング可" and p["credit"] == "撮影者名"


def test_research_archive_read_only_and_reapproval():
    store = seeded()
    t = approve(store, store.themes()[0])
    research = ResearchStore(store)
    facility(research, t["id"])
    store.review(t["id"], t["version"], t["title"], t["outline"], "", "修正済み")
    at = ui("施設候補リサーチ")
    assert at.warning and not at.button
    current = next(x for x in store.themes() if x["id"] == t["id"])
    approve(store, current)
    at.run()
    assert not at.exception
    assert any(b.label == "施設候補を更新" for b in at.button)


def test_default_app_pages_do_not_open_network(monkeypatch):
    seeded()
    def forbidden(*args, **kwargs):
        pytest.fail("Unexpected network connection from default application")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    at = ui("ダッシュボード")
    for page in ("AI投稿テーマ企画", "投稿制作の進捗管理", "過去の投稿実績", "施設候補リサーチ"):
        at.sidebar.radio[0].set_value(page).run()
        assert not at.exception
    at.sidebar.radio[0].set_value("AI投稿テーマ企画").run()
    element(at, "button", "テーマ10案を作成").click().run()
    assert not at.exception
    assert len(Store().themes()) == 20


# Known-defect acceptance tests below remain failing until separately approved fixes.
def test_stale_theme_save_must_explain_conflict():
    store = seeded()
    at = ui("AI投稿テーマ企画")
    t = sorted(store.themes(), key=lambda t: (-t["score"], t["id"]))[0]
    store.review(t["id"], t["version"], "別画面の更新", t["outline"], "", "承認")
    at.text_input[0].set_value("古い画面の編集")
    element(at, "button", "修正を保存").click().run()
    assert not at.exception
    assert next(x for x in store.themes() if x["id"] == t["id"])["title"] == "別画面の更新"
    assert at.error or at.warning, "QA-01: stale theme submission is silently discarded"


def test_stale_facility_save_must_explain_conflict():
    store = seeded()
    t = approve(store, store.themes()[0])
    research = ResearchStore(store)
    fid = facility(research, t["id"])
    at = ui("施設候補リサーチ")
    facility(research, t["id"], facility_id=fid, version=0, name="別画面の施設更新")
    element(at, "text_input", "施設名", 1).set_value("古い施設編集")
    element(at, "button", "施設候補を更新").click().run()
    assert not at.exception
    assert research.facilities(t["id"])[0]["name"] == "別画面の施設更新"
    assert at.error or at.warning, "QA-01: stale facility submission is silently discarded"


def test_performance_storage_must_reject_future_date():
    store = Store()
    with pytest.raises(ValueError):
        store.add_performance("未来の投稿", "暮らし", today()+timedelta(days=1), 100, 1, 1)
    assert store.performance() == [], "QA-02: future performance must not affect scoring"


def test_performance_storage_must_reject_boolean_count():
    store = Store()
    with pytest.raises(ValueError):
        store.add_performance("真偽値の数値", "暮らし", today(), True, 0, 0)
    assert store.performance() == [], "QA-03: bool must not be stored as a view count"
