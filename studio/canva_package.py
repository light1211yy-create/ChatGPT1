"""Offline Canva handoff: 7-page copy/asset manifest from approved facilities.

No network, image download, paid API, external uploader, or DB writes.
Existing Canva template is preserved; assets must be placed there by the operator.
"""
import csv
from datetime import date
from io import BytesIO, StringIO
import json
import re
from zipfile import ZipFile, ZIP_DEFLATED

from studio.research import ResearchStore, effective_permission, today


class CanvaPackageError(ValueError):
    """Safe, user-visible export validation errors."""


def _csv_value(value):
    """Avoid spreadsheet formula injection in exports originating from external data."""
    value = "" if value is None else str(value)
    if value.lstrip().startswith(("=", "+", "-", "@")) or value[:1] in ("\t", "\r", "\n"):
        return "'" + value
    return value


def _csv_bytes(headers, rows):
    buf = StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([_csv_value(row.get(h, "")) for h in headers])
    return buf.getvalue().encode("utf-8-sig")


def _photo_is_reusable(photo, today_value):
    """Conservative eligibility; recorded '利用可' alone is not permission for TikTok."""
    if effective_permission(photo, today_value) != "利用可":
        return False
    evidence = photo.get("evidence") or ""
    owner = photo.get("owner") or ""
    scope = photo.get("usage_scope") or ""
    if not (owner.strip() and evidence.strip() and scope.strip()):
        return False
    blocked = any(word in scope for word in (
        "加工不可", "加工禁止", "文字重ね不可", "文字重ね禁止",
        "トリミング不可", "トリミング禁止", "編集不可", "編集禁止",
        "商用不可", "商用禁止", "TikTok不可", "SNS不可"))
    commercial = any(word in scope for word in ("商用", "営利", "広告"))
    sns = any(word.lower() in scope.lower() for word in ("TikTok", "SNS", "ソーシャルメディア"))
    edit = any(word in scope for word in ("加工可", "文字重ね可", "トリミング可",
                                          "編集可", "加工許可", "文字重ね許可",
                                          "トリミング許可", "編集許可"))
    return not blocked and commercial and sns and edit


def build_canva_package(store, theme_id, facility_ids, *, today_value=None):
    """Return (zip_bytes, safe_filename, stats). Requires explicit five chosen facilities.

    Only rights-reviewed photo page URLs appear in page slots. Original image binaries
    are deliberately not fetched. Every facility fact remains marked unverified.
    """
    today_value = today_value or today()
    if type(today_value) is not date:
        raise CanvaPackageError("制作日の形式が不正です。")
    if type(theme_id) is not int or type(facility_ids) not in (list, tuple):
        raise CanvaPackageError("テーマ・施設選択が不正です。")
    if (len(facility_ids) != 5 or any(type(fid) is not int for fid in facility_ids)
            or len(set(facility_ids)) != 5):
        raise CanvaPackageError("異なる5施設を選択してください。")
    themes = {t["id"]: t for t in store.themes()}
    theme = themes.get(theme_id)
    if theme is None or theme["status"] != "承認":
        raise CanvaPackageError("承認済みテーマだけ制作パックを作成できます。")
    research = ResearchStore(store)
    by_id = {f["id"]: f for f in research.facilities(theme_id)}
    if any(fid not in by_id or by_id[fid]["candidate_status"] == "見送り" for fid in facility_ids):
        raise CanvaPackageError("選択した施設が見つからないか、見送りになっています。")

    pages = []
    review = []
    source_rows = []
    manifest_pages = []
    selected_names = []
    photo_filled = 0

    def add_page(number, kind, title, subtitle, facility="", upper="", lower="", note=""):
        row = {
            "ページ": number, "種類": kind, "見出し": title, "サブコピー": subtitle,
            "施設名": facility, "上写真の掲載元URL": upper, "下写真の掲載元URL": lower,
            "制作メモ": note,
        }
        pages.append(row)
        manifest_pages.append({
            "page": number, "type": kind, "title": title, "subtitle": subtitle,
            "facility": facility, "top_photo_source_page": upper,
            "bottom_photo_source_page": lower, "note": note,
        })

    add_page(1, "表紙", theme["title"], "気になる施設をまとめてチェック",
             note="既存Canvaテンプレートを使用。表紙用の画像も別途権利確認してください。")

    for index, fid in enumerate(facility_ids, 1):
        facility = by_id[fid]
        name = facility["name"]
        selected_names.append(name)
        photo_list = research.photos(fid)
        usable = [p for p in photo_list if _photo_is_reusable(p, today_value)]
        chosen_photos = usable[:2]
        photo_filled += len(chosen_photos)
        urls = [p["url"] for p in chosen_photos] + [""] * (2 - len(chosen_photos))
        facility_notes = "住所・価格・設備等は公式出典の再確認が必要。写真は掲載元への参照URLであり画像ファイルではありません。"
        add_page(index + 1, "施設紹介", f"{index:02d}｜{name}",
                 "掲載情報・料金・利用条件は投稿前に公式情報で確認",
                 facility=name, upper=urls[0], lower=urls[1], note=facility_notes)
        source_rows.append({
            "施設名": name, "公式サイト候補（未検証）": facility.get("official_url", ""),
            "住所（未検証）": facility.get("address", ""),
            "料金条件（未検証）": facility.get("price_note", ""),
            "確認日（記録値）": facility.get("checked_on", ""),
            "掲載前に確認すること": "公式施設・住所・予約条件・営業状況・必要なクレジット",
        })
        for p in photo_list:
            review.append({
                "施設名": name, "写真名": p.get("label", ""), "掲載元URL": p.get("url", ""),
                "記録された権利者": p.get("owner", ""),
                "記録された許諾範囲": p.get("usage_scope", ""),
                "許諾の根拠（記録）": p.get("evidence", ""),
                "利用期限": p.get("expires_on") or "",
                "管理上の状態": effective_permission(p, today_value),
                "TikTok商用編集向け候補": "候補URL（公開前に要最終確認）" if p in chosen_photos else "要確認・このパックのページに未採用",
            })

    add_page(7, "締め", "気になる場所は保存してあとでチェック",
             "最新情報は公式サイトで確認してね",
             note="CTA・ハッシュタグ・投稿音源は公開前に最終確認。画像や音源は含みません。")

    manifest = {
        "project": "MAKASE AI Studio",
        "format": "Canva copy-paste storyboard for existing top/bottom two-photo template",
        "theme_id": theme_id, "theme_title": theme["title"],
        "generated_on": today_value.isoformat(),
        "facility_ids": facility_ids, "facility_names": selected_names,
        "selected_photo_source_slots": photo_filled, "required_facility_photo_slots": 10,
        "photos_embedded": False, "canva_edited": False, "posted": False,
        "facts_officially_verified_by_app": False,
        "pages": manifest_pages,
        "notice": "公開前に公式情報・写真権利・実際の写真と施設の一致を確認してください。",
    }

    guide = [
        "# MAKASE｜Canva制作パック（7ページ）",
        f"テーマ：{theme['title']}",
        "",
        "既存のCanvaテンプレート（写真を上下に2枚配置）を開き、pages.csvの文章をコピーしてください。",
        "このパックはテキスト・候補写真ページURL・権利チェック情報のみで、画像ファイルやCanvaデザインは含みません。",
        "CSVはUTF-8（BOM付き）です。既存の無料Canvaで一括差し込みが可能とは保証していません。",
        "",
        "## 各ページ",
    ]
    for p in manifest_pages:
        guide += [
            f"### {p['page']}. {p['title']}",
            f"サブコピー：{p['subtitle']}",
            f"上写真の掲載元：{p['top_photo_source_page'] or '未設定／確認待ち'}",
            f"下写真の掲載元：{p['bottom_photo_source_page'] or '未設定／確認待ち'}",
            f"確認メモ：{p['note']}",
            "",
        ]
    guide += [
        "## 公開前チェック",
        "- 施設の存在・所在地・料金・営業時間等を公式サイトで再確認する",
        "- 使用する写真が対象施設を写しているか確認する",
        "- 商用TikTok・文字重ね・トリミング・二次利用・クレジット条件を写真ごとに確認する",
        "- 期限切れ・未許諾素材は使わず、必要なら差し替える",
        "- 投稿音源、広告／アフィリエイト表記、情報の更新日を確認する",
        "- OpenStreetMapを出典に使う場合は© OpenStreetMap contributors / ODbLの帰属表示を確認する",
        "",
        "このファイルの生成はオフラインで、API通信・DB変更・画像ダウンロード・自動投稿を行いません。",
    ]
    files = {
        "pages.csv": _csv_bytes(list(pages[0]), pages),
        "source_checklist.csv": _csv_bytes(list(source_rows[0]), source_rows),
        "photo_rights.csv": _csv_bytes(
            ["施設名", "写真名", "掲載元URL", "記録された権利者", "記録された許諾範囲",
             "許諾の根拠（記録）", "利用期限", "管理上の状態", "TikTok商用編集向け候補"], review),
        "manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        "README.md": ("\n".join(guide) + "\n").encode("utf-8"),
    }
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        for path, data in files.items():
            package.writestr(path, data)
    filename = f"makase_canva_theme_{theme_id}_{today_value:%Y%m%d}.zip"
    return output.getvalue(), filename, {
        "pages": 7, "facility_count": 5,
        "photo_source_slots": photo_filled,
        "missing_photo_slots": 10 - photo_filled,
        "confirmed_facts": False,
    }
