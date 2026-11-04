from datetime import timedelta

import pytest

from studio.db import ConflictError, Store
from studio.generator import PlanningContext
from studio.planning import generate_and_save
from studio.research import ResearchStore, effective_permission, today


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path / "research.sqlite3")
    generate_and_save(store, PlanningContext(today()))
    theme = store.themes()[0]
    store.review(theme["id"], theme["version"], theme["title"], theme["outline"], "", "承認")
    return store, ResearchStore(store), theme["id"]


def facility(research, theme_id, **changes):
    values = dict(name="テスト施設", address="東京都テスト区1-2-3", official_url="https://example.com/facility",
                  summary="営業時間は公式情報を確認", price_note="宿泊日・人数で変動", checked_on=today())
    values.update(changes)
    return research.save_facility(theme_id, **values)


def source(research, facility_id, **changes):
    values = dict(label="営業時間", fact="10:00〜18:00", source_url="https://example.com/hours", checked_on=today())
    values.update(changes)
    return research.save_source(facility_id, **values)


def photo(research, facility_id, **changes):
    values = dict(label="外観", photo_url="https://example.com/photo", owner="撮影者本人",
                  permission_status="利用可", evidence="テスト用許諾書の参照先", usage_scope="商用SNS動画・トリミング可")
    values.update(changes)
    return research.save_photo(facility_id, **values)


def test_candidates_sources_and_permissions_survive_restart(setup):
    store, research, theme_id = setup
    one = facility(research, theme_id)
    two = facility(research, theme_id, name="比較施設", candidate_status="優先候補")
    source(research, one)
    photo(research, one, expires_on=today() + timedelta(days=1))
    reopened = ResearchStore(Store(store.path))
    assert [f["id"] for f in reopened.facilities(theme_id)] == [one, two]
    assert reopened.facilities(theme_id)[1]["candidate_status"] == "優先候補"
    assert reopened.sources(one)[0]["checked_on"] == today().isoformat()
    assert reopened.sources(two) == []
    assert len(reopened.usable_photos(one)) == 1
    assert reopened.usable_photos(one, on=today() + timedelta(days=2)) == []
    assert effective_permission(reopened.photos(one)[0], today() + timedelta(days=2)) == "期限切れ"


def test_unapproved_theme_and_revocation(setup):
    store, research, theme_id = setup
    unapproved = next(t for t in store.themes() if t["status"] == "未承認")
    with pytest.raises(ValueError, match="承認済み"):
        facility(research, unapproved["id"])
    fid = facility(research, theme_id)
    sid = source(research, fid)
    pid = photo(research, fid)
    theme = next(t for t in store.themes() if t["id"] == theme_id)
    store.review(theme_id, theme["version"], theme["title"], theme["outline"], "", "却下")
    operations = [lambda: facility(research, theme_id), lambda: facility(research, theme_id, facility_id=fid),
                  lambda: source(research, fid), lambda: source(research, fid, source_id=sid),
                  lambda: photo(research, fid), lambda: photo(research, fid, photo_id=pid)]
    for operation in operations:
        with pytest.raises(ValueError, match="承認済み"):
            operation()
    assert len(research.facilities(theme_id)) == len(research.sources(fid)) == len(research.photos(fid)) == 1


def test_edits_and_stale_editor_are_guarded(setup):
    _, research, theme_id = setup
    fid = facility(research, theme_id)
    facility(research, theme_id, facility_id=fid, version=0, name="修正した施設")
    with pytest.raises(ConflictError):
        facility(research, theme_id, facility_id=fid, version=0, name="古い編集")
    sid = source(research, fid)
    source(research, fid, source_id=sid, version=0, fact="11:00〜18:00")
    with pytest.raises(ConflictError):
        source(research, fid, source_id=sid, version=0)
    pid = photo(research, fid)
    photo(research, fid, photo_id=pid, version=0, permission_status="利用不可")
    with pytest.raises(ConflictError):
        photo(research, fid, photo_id=pid, version=0)
    assert research.facilities(theme_id)[0]["name"] == "修正した施設"
    assert research.sources(fid)[0]["fact"] == "11:00〜18:00"
    assert research.usable_photos(fid) == []


def test_child_records_cannot_move_to_another_facility(setup):
    _, research, theme_id = setup
    one = facility(research, theme_id)
    two = facility(research, theme_id, name="別の施設")
    sid = source(research, one)
    pid = photo(research, one)
    with pytest.raises(ConflictError):
        source(research, two, source_id=sid)
    with pytest.raises(ConflictError):
        photo(research, two, photo_id=pid)
    assert research.sources(two) == research.photos(two) == []


@pytest.mark.parametrize("bad_url", ["javascript:alert(1)", "file:///private", "https://user:secret@example.com", "https://", "https://example.com/with space"])
def test_invalid_urls_not_saved(setup, bad_url):
    _, research, theme_id = setup
    with pytest.raises(ValueError):
        facility(research, theme_id, official_url=bad_url)
    assert research.facilities(theme_id) == []


def test_future_confirmation_date_not_saved(setup):
    _, research, theme_id = setup
    with pytest.raises(ValueError, match="確認日"):
        facility(research, theme_id, checked_on=today() + timedelta(days=1))
    fid = facility(research, theme_id)
    with pytest.raises(ValueError, match="確認日"):
        source(research, fid, checked_on=today() + timedelta(days=1))
    assert research.sources(fid) == []


@pytest.mark.parametrize("changes", [{"owner": ""}, {"evidence": ""}, {"usage_scope": ""}, {"expires_on": today() - timedelta(days=1)}])
def test_usable_photo_requires_permission_evidence(setup, changes):
    _, research, theme_id = setup
    fid = facility(research, theme_id)
    with pytest.raises(ValueError):
        photo(research, fid, **changes)
    assert research.photos(fid) == []


@pytest.mark.parametrize("status", ["未確認", "利用不可", "期限切れ"])
def test_nonusable_photo_not_in_usable_list(setup, status):
    _, research, theme_id = setup
    fid = facility(research, theme_id)
    photo(research, fid, permission_status=status)
    assert len(research.photos(fid)) == 1
    assert research.usable_photos(fid) == []


def test_additive_schema_preserves_phase1_data(tmp_path):
    store = Store(tmp_path / "old.sqlite3")
    generate_and_save(store, PlanningContext(today()))
    theme = store.themes()[0]
    store.review(theme["id"], 0, theme["title"], theme["outline"], "承認記録", "承認")
    store.set_progress(theme["id"], 1, "編集", "編集中")
    store.add_performance("過去投稿", "暮らし", today(), 100, 10, 1)
    before = (store.themes(), store.batches(), store.audit(theme["id"]), store.performance())
    for _ in range(2):
        ResearchStore(Store(store.path))
    assert (store.themes(), store.batches(), store.audit(theme["id"]), store.performance()) == before
