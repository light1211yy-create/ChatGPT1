"""Make the Canva production entry discoverable before any facilities exist.

These are offline UI tests with temporary databases only.
"""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from studio.db import Store
from studio.generator import PlanningContext
from studio.planning import generate_and_save
from studio.research import ResearchStore, today

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("MAKASE_DB_PATH", str(tmp_path / "visibility.sqlite3"))
    store = Store(tmp_path / "visibility.sqlite3")
    generate_and_save(store, PlanningContext(today()))
    theme = store.themes()[0]
    store.review(theme["id"], theme["version"], theme["title"], theme["outline"], "", "承認")
    return store, ResearchStore(store), theme["id"]


def open_research():
    at = AppTest.from_file(str(APP), default_timeout=20).run()
    at.sidebar.radio[0].set_value("施設候補リサーチ").run()
    assert not at.exception
    return at


def canva_panels(at):
    return [e for e in at.get("expander")
            if "Canva用7ページ制作パック" in e.label]


def facility(research, theme_id, number):
    return research.save_facility(
        theme_id, name=f"テストホテル{number}", address="架空住所",
        official_url=f"https://example.org/hotel{number}",
        summary="未確認", price_note="未確認", checked_on=today())


def test_canva_entry_appears_for_approved_theme_without_facilities(setup):
    _, research, tid = setup
    assert research.facilities(tid) == []
    at = open_research()
    assert len(canva_panels(at)) == 1
    assert any("5施設が必要" in i.value for i in at.info)


def test_canva_entry_appears_before_five_facilities(setup):
    _, research, tid = setup
    facility(research, tid, 1)
    at = open_research()
    assert len(canva_panels(at)) == 1
    assert any("5施設が必要" in i.value for i in at.info)


def test_canva_entry_appears_with_five_facilities(setup):
    _, research, tid = setup
    for i in range(5):
        facility(research, tid, i)
    at = open_research()
    assert len(canva_panels(at)) == 1
    assert len([m for m in at.get("multiselect") if m.label == "紹介する施設5件（表示順）"]) == 1


def test_canva_entry_not_shown_for_revoked_theme(setup):
    store, research, tid = setup
    facility(research, tid, 1)
    current = next(t for t in store.themes() if t["id"] == tid)
    store.review(tid, current["version"], current["title"], current["outline"], "", "却下")
    at = open_research()
    assert canva_panels(at) == []
