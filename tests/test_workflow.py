from datetime import date

import pytest

from studio.db import ConflictError, Store
from studio.generator import OfflineThemeGenerator, PlanningContext


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "test.sqlite3")


def batch(store):
    context = PlanningContext(date(2026, 11, 4))
    return store.save_batch(context, OfflineThemeGenerator.name, OfflineThemeGenerator().generate(context, store.performance()))


def review(store, theme, status, title="修正した企画"):
    store.review(theme["id"], theme["version"], title, theme["outline"], "判断の記録", status)


def test_ten_themes_and_season():
    generator = OfflineThemeGenerator()
    drafts = generator.generate(PlanningContext(date(2026, 11, 4)), [])
    assert len(drafts) == len({d.title for d in drafts}) == 10
    assert all(0 <= d.score <= 100 for d in drafts)
    assert all("日本在住18〜34歳" in d.reason and "秋" in d.reason and "紅葉" in d.reason for d in drafts)
    winter = generator.generate(PlanningContext(date(2026, 1, 4)), [])
    assert all("冬" in d.reason and "お正月" in d.reason for d in winter)
    assert [d.title for d in drafts] != [d.title for d in winter]


def test_history_changes_category_score(store):
    generator = OfflineThemeGenerator()
    context = PlanningContext(date(2026, 11, 4), "グルメ", "顔出しなし")
    before = {d.title: d.score for d in generator.generate(context, [])}
    store.add_performance("実際の投稿", "暮らし", date(2026, 10, 1), 1000, 80, 20)
    after = generator.generate(context, store.performance())
    for draft in after:
        assert draft.score == before[draft.title] + (10 if draft.category == "暮らし" else 0)
        assert "顔出しなし" in draft.reason


def test_full_lifecycle_is_persistent(store):
    batch_id = batch(store)
    theme = store.themes(batch_id)[0]
    review(store, theme, "修正済み")
    theme = store.themes(batch_id)[0]
    assert theme["title"] == "修正した企画"
    review(store, theme, "承認")
    theme = store.themes(batch_id)[0]
    store.set_progress(theme["id"], theme["version"], "編集", "動画を編集中")
    reopened = Store(store.path)
    theme = reopened.themes(batch_id)[0]
    assert theme["status"] == "承認" and theme["progress"] == "編集"
    assert theme["note"] == "動画を編集中"
    review(reopened, theme, "却下")
    theme = store.themes(batch_id)[0]
    assert theme["status"] == "却下" and theme["progress"] == "未着手"
    assert len(store.audit(theme["id"])) == 4


def test_new_batch_preserves_existing(store):
    first = batch(store)
    second = batch(store)
    assert first != second
    assert len(store.themes(first)) == len(store.themes(second)) == 10
    assert len(store.themes()) == 20


def test_unapproved_progress_is_rejected(store):
    batch_id = batch(store)
    theme = store.themes(batch_id)[0]
    with pytest.raises(ConflictError):
        store.set_progress(theme["id"], theme["version"], "完成", "")
    assert store.themes(batch_id)[0]["progress"] == "未着手"
    assert store.audit(theme["id"]) == []


def test_stale_editor_cannot_overwrite(store):
    theme = store.themes(batch(store))[0]
    review(store, theme, "承認", "最新の企画")
    with pytest.raises(ConflictError):
        review(store, theme, "却下", "古い編集")
    assert store.themes()[0]["title"] == "最新の企画"
    assert len(store.audit(theme["id"])) == 1


@pytest.mark.parametrize("title,status", [("  ", "承認"), ("タイトル", "不正な状態"), ("a" * 151, "承認")])
def test_invalid_review_does_not_mutate(store, title, status):
    theme = store.themes(batch(store))[0]
    with pytest.raises(ValueError):
        review(store, theme, status, title)
    assert store.themes()[0] == theme


@pytest.mark.parametrize("views,likes,saves", [(-1, 0, 0), (100, 101, 0), (0, 0, 1)])
def test_invalid_performance(store, views, likes, saves):
    with pytest.raises(ValueError):
        store.add_performance("投稿", "暮らし", date(2026, 1, 1), views, likes, saves)
    assert store.performance() == []


def test_invalid_batch_is_not_saved(store):
    with pytest.raises(ValueError):
        store.save_batch(PlanningContext(date(2026, 1, 1)), "test", [])
    assert store.batches() == []
