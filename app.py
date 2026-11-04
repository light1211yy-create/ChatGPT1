"""Run with: python -m streamlit run app.py"""
import json
from datetime import datetime, timedelta, timezone

import streamlit as st

from studio.db import PROGRESS, Store
from studio.generator import CATEGORIES, PlanningContext
from studio.planning import generate_and_save
from studio.research_ui import research_page

st.set_page_config(page_title="MAKASE AI Studio", page_icon="🎬", layout="wide")


def today():
    return datetime.now(timezone(timedelta(hours=9))).date()


def table(themes):
    return [{"ID": t["id"], "テーマ": t["title"], "ジャンル": t["category"],
             "スコア": t["score"], "承認状態": t["status"], "制作進捗": t["progress"]} for t in themes]


def flash(message):
    st.session_state["notice"] = message
    st.rerun()


def dashboard(store):
    st.header("ダッシュボード")
    st.write("企画から承認、投稿制作まで。今日の作業をここから始めましょう。")
    themes = store.themes()
    metrics = st.columns(4)
    metrics[0].metric("企画テーマ", len(themes))
    metrics[1].metric("承認待ち", sum(t["status"] in ("未承認", "修正済み") for t in themes))
    metrics[2].metric("制作中", sum(t["status"] == "承認" and t["progress"] not in ("完成", "投稿済み") for t in themes))
    metrics[3].metric("投稿済み", sum(t["progress"] == "投稿済み" for t in themes))
    st.subheader("制作ステータス")
    approved = [t for t in themes if t["status"] == "承認"]
    st.bar_chart({"件数": {p: sum(t["progress"] == p for t in approved) for p in PROGRESS}})
    st.subheader("最近のテーマ")
    if themes:
        st.dataframe(table(themes[:10]), hide_index=True, width="stretch")
    else:
        st.info("まだ企画はありません。「AI投稿テーマ企画」から10案を作成してください。")
    st.caption("テーマ企画・承認・制作進捗・施設候補管理。Canva制作・TikTok投稿は未接続です。")


def planner(store):
    st.header("AI投稿テーマ企画")
    st.info("無料テストモード：AIモデルには接続していません。ルールベースで10案を作成し、追加課金や外部へのデータ送信は発生しません。")
    st.write("対象：日本在住18〜34歳。季節・月ごとのイベント・過去の投稿実績を企画の参考にします。")
    with st.form("planning"):
        target = st.date_input("企画対象日", today())
        focus = st.selectbox("重点ジャンル", CATEGORIES)
        brief = st.text_area("企画メモ（任意）", max_chars=500, placeholder="例：顔出しなし、予算1,000円以内")
        st.caption("テストモードでは企画メモを条件として添付します。内容への自動反映はしません。")
        generate = st.form_submit_button("テーマ10案を作成", type="primary")
    if generate:
        try:
            context = PlanningContext(target, focus, brief)
            batch_id = generate_and_save(store, context)
            st.session_state["selected_batch"] = batch_id
            flash(f"企画 #{batch_id} に10案を保存しました。下の一覧から承認・修正・却下できます。")
        except ValueError as exc:
            st.error(str(exc))
    batches = store.batches()
    if not batches:
        return
    labels = {}
    for b in batches:
        context = json.loads(b["context"])
        labels[b["id"]] = f"企画 #{b['id']}｜対象 {context['target_date']}｜{context['focus']}"
    ids = [b["id"] for b in batches]
    if st.session_state.get("selected_batch") not in ids:
        st.session_state["selected_batch"] = ids[0]
    batch_id = st.selectbox("企画履歴", ids, format_func=labels.get, key="selected_batch")
    st.caption(next(b["provider"] for b in batches if b["id"] == batch_id))
    st.caption("スコア（0〜100）：基本65点＋重点ジャンル10点＋過去実績の反応率に応じた最大20点。再生数の予測ではありません。イベントは固定の月別候補で、最新の開催情報は制作時に確認してください。")
    themes = sorted(store.themes(batch_id), key=lambda t: (-t["score"], t["id"]))
    st.subheader(f"投稿テーマ {len(themes)}案")
    st.dataframe(table(themes), hide_index=True, width="stretch")
    for index, theme in enumerate(themes, start=1):
        with st.expander(f"{index:02d}｜{theme['score']}点｜{theme['title']}｜{theme['status']}", expanded=index == 1):
            st.markdown("**企画理由**")
            st.write(theme["reason"])
            # Versioned widget keys prevent stale editors overwriting new database values.
            key = f"{theme['id']}_{theme['version']}"
            with st.form(f"review_{key}"):
                title = st.text_input("テーマ名", theme["title"], max_chars=150, key=f"title_{key}")
                outline = st.text_area("投稿構成", theme["outline"], max_chars=2000, key=f"outline_{key}")
                note = st.text_area("判断理由・制作メモ", theme["note"], max_chars=1000, key=f"note_{key}")
                st.caption("編集した内容は、選んだ操作と同時に保存されます。承認を取り消すと進捗は未着手に戻ります。")
                cols = st.columns(3)
                approve = cols[0].form_submit_button("承認", type="primary")
                revise = cols[1].form_submit_button("修正を保存")
                reject = cols[2].form_submit_button("却下")
            if approve or revise or reject:
                status = "承認" if approve else "修正済み" if revise else "却下"
                try:
                    store.review(theme["id"], theme["version"], title, outline, note, status)
                    flash(f"テーマ #{theme['id']} を「{status}」として保存しました。")
                except ValueError as exc:
                    st.error(str(exc))
            audit = store.audit(theme["id"])
            if audit:
                st.caption("変更履歴（日本時間）")
                st.dataframe([{"日時": a["created_at"], "操作": a["action"], "内容": a["details"]} for a in audit], hide_index=True, width="stretch")


def production(store):
    st.header("投稿制作の進捗管理")
    st.write("承認したテーマの構成作成から投稿完了までを管理します。自動投稿は行いません。")
    approved = [t for t in store.themes() if t["status"] == "承認"]
    if not approved:
        st.info("承認されたテーマはありません。テーマ企画の一覧で承認してください。")
        return
    selected = st.selectbox("進捗で絞り込み", ("すべて",) + PROGRESS)
    visible = [t for t in approved if selected == "すべて" or t["progress"] == selected]
    st.dataframe(table(visible), hide_index=True, width="stretch")
    for theme in visible:
        key = f"progress_{theme['id']}_{theme['version']}"
        with st.expander(f"#{theme['id']} {theme['title']}｜{theme['progress']}", expanded=True):
            st.write(theme["outline"])
            with st.form(key):
                progress = st.selectbox("制作進捗", PROGRESS, index=PROGRESS.index(theme["progress"]), key=f"stage_{key}")
                note = st.text_area("制作メモ", theme["note"], max_chars=1000, key=f"memo_{key}")
                submitted = st.form_submit_button("進捗を保存")
            if submitted:
                try:
                    store.set_progress(theme["id"], theme["version"], progress, note)
                    flash("制作進捗を保存しました。")
                except ValueError as exc:
                    st.error(str(exc))


def performance(store):
    st.header("過去の投稿実績")
    st.write("実際の投稿数値を手入力します。登録した実績は、次回作成するテーマのジャンル別スコアに反映されます。")
    with st.form("performance", clear_on_submit=True):
        title = st.text_input("投稿タイトル", max_chars=150)
        category = st.selectbox("ジャンル", CATEGORIES)
        posted = st.date_input("投稿日", today(), max_value=today())
        cols = st.columns(3)
        views = cols[0].number_input("再生数", min_value=0, step=1)
        likes = cols[1].number_input("いいね数", min_value=0, step=1)
        saves = cols[2].number_input("保存数", min_value=0, step=1)
        submitted = st.form_submit_button("実績を登録")
    if submitted:
        try:
            store.add_performance(title, category, posted, views, likes, saves)
            flash("投稿実績を保存しました。次回の企画から反映されます。")
        except ValueError as exc:
            st.error(str(exc))
    rows = store.performance()
    if rows:
        st.dataframe([{"投稿": r["title"], "ジャンル": r["category"], "投稿日": r["posted_on"],
                       "再生": r["views"], "いいね": r["likes"], "保存": r["saves"]} for r in rows], hide_index=True, width="stretch")
    else:
        st.info("実績は未登録です。実績がなくてもテーマを作成できます。")


def main():
    st.title("🎬 MAKASE AI Studio")
    st.caption("日本語コンテンツ制作の企画・承認ワークスペース")
    st.sidebar.title("MAKASE")
    page = st.sidebar.radio("メニュー", ("ダッシュボード", "AI投稿テーマ企画", "投稿制作の進捗管理", "過去の投稿実績", "施設候補リサーチ"))
    st.sidebar.caption("Phase 2 · 無料テストモード\n\nデータはこの端末のSQLiteに保存されます。")
    if "notice" in st.session_state:
        st.success(st.session_state.pop("notice"))
    store = Store()
    {"ダッシュボード": dashboard, "AI投稿テーマ企画": planner,
     "投稿制作の進捗管理": production, "過去の投稿実績": performance, "施設候補リサーチ": research_page}[page](store)


if __name__ == "__main__":
    main()
