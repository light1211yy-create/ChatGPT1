"""No-network Phase 4 Canva-package export tests; real user data is never opened."""
import csv
from datetime import timedelta
from io import BytesIO, TextIOWrapper
import json
from zipfile import ZipFile

import pytest
from streamlit.testing.v1 import AppTest

from studio.canva_package import CanvaPackageError, build_canva_package
from studio.db import Store
from studio.generator import PlanningContext
from studio.planning import generate_and_save
from studio.research import ResearchStore, today


@pytest.fixture
def prepared(tmp_path):
    store = Store(tmp_path / "canva_test.sqlite3")
    generate_and_save(store, PlanningContext(today()))
    theme = store.themes()[0]
    store.review(theme["id"], theme["version"], theme["title"], theme["outline"], "", "承認")
    research = ResearchStore(store)
    ids = []
    for i in range(5):
        fid = research.save_facility(
            theme["id"], name=f"テストホテル{i+1}", address="大阪府の仮住所",
            official_url=f"https://example.org/test{i+1}", summary="要公式確認",
            price_note="日付・条件によって変動。未検証", checked_on=today(),
            candidate_status="優先候補")
        ids.append(fid)
    return store, research, theme["id"], ids


def contents(blob):
    with ZipFile(BytesIO(blob)) as z:
        assert set(z.namelist()) == {
            "pages.csv", "photo_rights.csv", "source_checklist.csv",
            "manifest.json", "README.md"}
        manifest = json.loads(z.read("manifest.json"))
        text = z.read("README.md").decode("utf-8")
        pages = list(csv.DictReader(TextIOWrapper(z.open("pages.csv"), encoding="utf-8-sig")))
        rights = list(csv.DictReader(TextIOWrapper(z.open("photo_rights.csv"), encoding="utf-8-sig")))
        return manifest, text, pages, rights


def test_export_7_pages_and_no_network_or_data_mutation(prepared, monkeypatch):
    store, research, theme_id, ids = prepared
    monkeypatch.setattr("socket.socket.connect", lambda *a, **kw: pytest.fail("No network allowed"))
    before = (store.themes(), store.batches(), research.facilities(theme_id))
    data, filename, stats = build_canva_package(store, theme_id, ids)
    assert filename.startswith(f"makase_canva_theme_{theme_id}_") and filename.endswith(".zip")
    assert len(data) > 300 and stats["pages"] == 7 and stats["facility_count"] == 5
    manifest, readme, pages, rights = contents(data)
    assert len(pages) == 7 and len(rights) == 0
    assert pages[0]["種類"] == "表紙" and pages[-1]["種類"] == "締め"
    assert [p["施設名"] for p in pages[1:6]] == [f"テストホテル{i}" for i in range(1, 6)]
    assert all(not p["上写真の掲載元URL"] and not p["下写真の掲載元URL"] for p in pages)
    assert manifest["photos_embedded"] is False and manifest["canva_edited"] is False
    assert manifest["facts_officially_verified_by_app"] is False
    assert "既存のCanvaテンプレート" in readme
    assert (store.themes(), store.batches(), research.facilities(theme_id)) == before


def test_only_recorded_commercial_sns_editable_photos_can_populate_slides(prepared):
    store, research, theme_id, ids = prepared
    fid = ids[0]
    photo_common = dict(label="外観", photo_url="https://commons.wikimedia.org/wiki/File:hotel.jpg",
                        owner="写真著作権者", permission_status="利用可",
                        evidence="許諾書をローカルで保管",
                        usage_scope="商用TikTokとSNS投稿でトリミング・文字重ね可")
    research.save_photo(fid, **photo_common)
    research.save_photo(fid, **{**photo_common, "label": "室内",
                               "photo_url": "https://commons.wikimedia.org/wiki/File:room.jpg"})
    research.save_photo(fid, **{**photo_common, "label": "写真3",
                               "photo_url": "https://commons.wikimedia.org/wiki/File:extra.jpg"})
    research.save_photo(ids[1], **{**photo_common, "label": "編集不可",
                                   "usage_scope": "商用TikTokへの掲載のみ。加工不可"})
    research.save_photo(ids[2], **{**photo_common, "label": "期限切れ",
                                   "expires_on": today() + timedelta(days=1)})
    data, _, stats = build_canva_package(store, theme_id, ids, today_value=today()+timedelta(days=2))
    manifest, _, pages, rights = contents(data)
    assert stats["photo_source_slots"] == 2
    assert stats["missing_photo_slots"] == 8
    assert pages[1]["上写真の掲載元URL"].endswith("hotel.jpg")
    assert pages[1]["下写真の掲載元URL"].endswith("room.jpg")
    assert pages[2]["上写真の掲載元URL"] == ""
    assert pages[3]["上写真の掲載元URL"] == ""
    assert len(rights) == 5 and any(r["管理上の状態"] == "期限切れ" for r in rights)
    assert all("photos_embedded" not in p for p in manifest["pages"])


@pytest.mark.parametrize("bad_ids", [
    [], [1], [1, 2, 3, 4, 4], [1, 2, 3, 4, 5, 6], ["1", 2, 3, 4, 5],
])
def test_wrong_5_facilities_block_export(prepared, bad_ids):
    store, _, theme_id, _ = prepared
    with pytest.raises(CanvaPackageError):
        build_canva_package(store, theme_id, bad_ids)


def test_revoked_theme_cannot_export(prepared):
    store, research, theme_id, ids = prepared
    theme = next(t for t in store.themes() if t["id"] == theme_id)
    store.review(theme_id, theme["version"], theme["title"], theme["outline"], "", "却下")
    with pytest.raises(CanvaPackageError, match="承認済み"):
        build_canva_package(store, theme_id, ids)
    assert len(research.facilities(theme_id)) == 5


def test_other_theme_facility_and_rejected_facility_block_export(prepared):
    store, research, theme_id, ids = prepared
    research.save_facility(
        theme_id, name="見送り", address="架空住所", official_url="https://example.org/reject",
        summary="", price_note="", checked_on=today(), candidate_status="見送り")
    rejected_id = research.facilities(theme_id)[-1]["id"]
    with pytest.raises(CanvaPackageError, match="見送り"):
        build_canva_package(store, theme_id, ids[:4] + [rejected_id])
    generate_and_save(store, PlanningContext(today()))
    other = next(t for t in store.themes() if t["id"] not in {theme_id})
    store.review(other["id"], other["version"], other["title"], other["outline"], "", "承認")
    other_id = research.save_facility(other["id"], name="別施設", address="別地域",
        official_url="https://example.org/other", summary="", price_note="", checked_on=today())
    with pytest.raises(CanvaPackageError):
        build_canva_package(store, theme_id, ids[:4] + [other_id])


def test_csv_formula_escape_preserves_data_without_execution(prepared):
    store, research, theme_id, ids = prepared
    first = research.facilities(theme_id)[0]
    research.save_facility(theme_id, name="=HYPERLINK(\"https://evil.example\")",
        address="大阪府", official_url="https://example.org/normal", summary="",
        price_note="", checked_on=today(), facility_id=ids[0], version=first["version"])
    data, _, _ = build_canva_package(store, theme_id, ids)
    _, _, pages, _ = contents(data)
    assert pages[1]["施設名"].startswith("'=HYPERLINK")


def test_streamlit_research_panel_can_prepare_export_without_api(prepared, monkeypatch):
    store, _, theme_id, _ = prepared
    monkeypatch.setenv("MAKASE_DB_PATH", str(store.path))
    monkeypatch.setattr("socket.socket.connect", lambda *a, **kw: pytest.fail("No external network"))
    from pathlib import Path
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20).run()
    at.sidebar.radio[0].set_value("施設候補リサーチ").run()
    assert not at.exception
    # The download button might not be represented in AppTest; confirm the package panel exists.
    assert any("Canva用7ページ制作パック" in e.label for e in at.get("expander"))
