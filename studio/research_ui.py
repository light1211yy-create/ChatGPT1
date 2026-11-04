"""Streamlit forms for manual facility comparison and photo rights."""
from datetime import date

import streamlit as st

from studio.research import CANDIDATE_STATUSES, PERMISSIONS, ResearchStore, effective_permission, today


def saved(message):
    st.session_state["notice"] = message
    st.rerun()


def facility_form(research, theme_id, facility=None):
    f = facility or {}
    key = f"facility_{theme_id}_{f.get('id', 'new')}_{f.get('version', 0)}"
    with st.form(key):
        name = st.text_input("施設名", f.get("name", ""), max_chars=150)
        address = st.text_input("住所", f.get("address", ""), max_chars=500)
        official = st.text_input("施設公式URL", f.get("official_url", ""), max_chars=2000)
        summary = st.text_area("施設情報・アクセス・営業時間", f.get("summary", ""), max_chars=2000)
        price = st.text_area("料金と条件（任意）", f.get("price_note", ""), max_chars=2000,
                             help="宿泊日・人数・部屋・食事・税や手数料などを併記してください。価格・空室の保証はしません。")
        checked = st.date_input("公式情報の確認日", date.fromisoformat(f["checked_on"]) if f else today(), max_value=today())
        status = st.selectbox("候補の状態", CANDIDATE_STATUSES, index=CANDIDATE_STATUSES.index(f.get("candidate_status", "検討中")))
        notes = st.text_area("比較メモ", f.get("notes", ""), max_chars=2000)
        submitted = st.form_submit_button("施設候補を更新" if f else "施設候補を登録", type="primary")
    if submitted:
        try:
            research.save_facility(theme_id, name=name, address=address, official_url=official,
                summary=summary, price_note=price, checked_on=checked, candidate_status=status, notes=notes,
                facility_id=f.get("id"), version=f.get("version", 0))
            saved("施設候補を保存しました。")
        except ValueError as exc:
            st.error(str(exc))


def source_editor(research, facility_id, sources):
    options = {s["id"]: s for s in sources}
    chosen = st.selectbox("編集する出典", [None] + list(options),
        format_func=lambda i: "新しい出典" if i is None else f"#{i} {options[i]['label']}", key=f"source_choice_{facility_id}")
    s = options.get(chosen, {})
    with st.form(f"source_{facility_id}_{chosen}_{s.get('version', 0)}"):
        label = st.text_input("確認項目", s.get("label", ""), max_chars=150, placeholder="例：営業時間")
        fact = st.text_area("確認した情報", s.get("fact", ""), max_chars=2000)
        source_url = st.text_input("出典URL", s.get("url", ""), max_chars=2000)
        checked = st.date_input("出典の確認日", date.fromisoformat(s["checked_on"]) if s else today(), max_value=today())
        notes = st.text_area("出典メモ", s.get("notes", ""), max_chars=2000)
        submitted = st.form_submit_button("出典を保存")
    if submitted:
        try:
            research.save_source(facility_id, label=label, fact=fact, source_url=source_url, checked_on=checked,
                                 notes=notes, source_id=chosen, version=s.get("version", 0))
            saved("出典を保存しました。")
        except ValueError as exc:
            st.error(str(exc))


def photo_editor(research, facility_id, photos):
    options = {p["id"]: p for p in photos}
    chosen = st.selectbox("編集する写真候補", [None] + list(options),
        format_func=lambda i: "新しい写真候補" if i is None else f"#{i} {options[i]['label']}", key=f"photo_choice_{facility_id}")
    p = options.get(chosen, {})
    with st.form(f"photo_{facility_id}_{chosen}_{p.get('version', 0)}"):
        label = st.text_input("写真名", p.get("label", ""), max_chars=150)
        photo_url = st.text_input("写真候補・掲載元URL", p.get("url", ""), max_chars=2000)
        owner = st.text_input("権利者", p.get("owner", ""), max_chars=300)
        permission = st.selectbox("利用許諾状況", PERMISSIONS, index=PERMISSIONS.index(effective_permission(p) if p else "未確認"))
        evidence = st.text_area("許諾の根拠", p.get("evidence", ""), max_chars=2000, help="許諾書の保管先や許諾元URLなど。秘密情報は入力しないでください。")
        scope = st.text_area("許諾された用途", p.get("usage_scope", ""), max_chars=2000,
                             help="商用SNS投稿・対象媒体・広告・加工の可否など。用途外の使用はできません。")
        credit = st.text_input("クレジット表記", p.get("credit", ""), max_chars=500)
        has_expiry = st.checkbox("利用期限あり", value=bool(p.get("expires_on")))
        expires = st.date_input("利用期限", date.fromisoformat(p["expires_on"]) if p.get("expires_on") else today())
        notes = st.text_area("写真メモ", p.get("notes", ""), max_chars=2000)
        submitted = st.form_submit_button("写真候補を保存")
    if submitted:
        try:
            research.save_photo(facility_id, label=label, photo_url=photo_url, owner=owner, permission_status=permission,
                evidence=evidence, usage_scope=scope, credit=credit, expires_on=expires if has_expiry else None,
                notes=notes, photo_id=chosen, version=p.get("version", 0))
            saved("写真候補と利用許諾を保存しました。")
        except ValueError as exc:
            st.error(str(exc))


def research_page(store):
    st.header("施設候補リサーチ")
    st.write("承認済みテーマごとに施設候補を手動で登録・比較します。公式情報を確認し、出典と確認日を残してください。")
    st.info("外部サイトの自動収集・画像取得・投稿は行いません。写真の「利用可」は入力した許諾内容に基づく管理状態です。実際の用途への適合は公開前に確認してください。")
    research = ResearchStore(store)
    themes = [t for t in store.themes() if t["status"] == "承認" or research.facilities(t["id"])]
    if not themes:
        st.info("施設候補を登録するには、先に「AI投稿テーマ企画」でテーマを承認してください。")
        return
    mapping = {t["id"]: t for t in themes}
    theme_id = st.selectbox("対象テーマ", list(mapping), format_func=lambda i: f"#{i} {mapping[i]['title']}｜{mapping[i]['status']}")
    approved = mapping[theme_id]["status"] == "承認"
    if approved:
        with st.expander("施設候補の新規登録"):
            facility_form(research, theme_id)
    else:
        st.warning("このテーマは承認が取り消されています。保存済み情報は閲覧のみ可能です。編集するにはテーマを再承認してください。")
    facilities = research.facilities(theme_id)
    if not facilities:
        st.info("施設候補はまだありません。上の新規登録から追加してください。")
        return
    by_id = {f["id"]: f for f in facilities}
    st.subheader("施設候補の比較")
    selected = st.multiselect("比較する施設", list(by_id), default=list(by_id),
                             format_func=lambda i: f"#{i} {by_id[i]['name']}", key=f"compare_{theme_id}")
    rows = []
    for facility_id in selected:
        f = by_id[facility_id]
        rows.append({"ID": f["id"], "施設名": f["name"], "候補の状態": f["candidate_status"],
            "住所": f["address"], "施設情報": f["summary"], "料金と条件": f["price_note"],
            "公式URL": f["official_url"], "確認日": f["checked_on"], "比較メモ": f["notes"],
            "追加出典数": len(research.sources(facility_id)), "利用可の写真数": len(research.usable_photos(facility_id))})
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
    else:
        st.info("比較する施設を選択してください。")
    st.caption("確認日時点の参考情報です。料金・空室・営業時間は投稿前に再確認してください。写真は許諾期限切れになると利用可の件数から自動で除外されます。")
    facility_id = st.selectbox("詳細を表示する施設", list(by_id), format_func=lambda i: f"#{i} {by_id[i]['name']}", key=f"detail_{theme_id}")
    facility = by_id[facility_id]
    if approved:
        with st.expander("施設情報を編集"):
            facility_form(research, theme_id, facility)
    st.subheader("項目別の出典")
    sources = research.sources(facility_id)
    if sources:
        st.dataframe([{"項目": s["label"], "確認した情報": s["fact"], "出典URL": s["url"],
                       "確認日": s["checked_on"], "メモ": s["notes"]} for s in sources], hide_index=True, width="stretch")
    if approved:
        with st.expander("出典を登録・修正"):
            source_editor(research, facility_id, sources)
    st.subheader("写真候補・利用許諾")
    photos = research.photos(facility_id)
    if photos:
        st.dataframe([{"写真名": p["label"], "掲載元URL": p["url"], "権利者": p["owner"],
            "利用許諾状況": effective_permission(p), "許諾の根拠": p["evidence"], "許諾された用途": p["usage_scope"],
            "クレジット": p["credit"], "利用期限": p["expires_on"] or "期限の指定なし", "メモ": p["notes"]}
            for p in photos], hide_index=True, width="stretch")
    st.caption("画像ファイルは取得・表示せず、参照先と権利情報を保存します。未確認・利用不可・期限切れの写真は利用可に数えません。")
    if approved:
        with st.expander("写真候補を登録・修正"):
            photo_editor(research, facility_id, photos)
