"""User-operated AI research panel; each external step requires explicit consent."""
import streamlit as st

from studio.auto_research import AIResearchError, MODEL, build_research
from studio.gemini import GeminiConsent
from studio.key_config import load_api_key


def research_ai_panel(research, theme_id, theme):
    st.subheader("AI施設リサーチ（試験版）")
    st.write("施設の候補探し・比較・おすすめ5件・写真候補の検索をAIと公開データで行います。"
             "調査結果は最初に未確認の下書きとして保存し、実際の投稿・画像ダウンロードは行いません。")
    st.caption("情報源：© OpenStreetMap contributors（ODbL）・Wikimedia Commons。"
               "公開データは古い・不完全な場合があります。Google Search Groundingや有料APIは使いません。")
    st.warning("施設の公式URL・価格・営業時間・写真の商用利用許諾は自動で確認済みにしません。"
               "写真の選定候補は、施設の写真ではない場合もあります。公開前の確認が必要です。")
    draft = research.latest_ai_draft(theme_id)
    if draft:
        st.markdown(f"**保存済みAI調査案 #{draft['id']}** — {draft['area']} / {draft['model']}")
        rows = draft["data"].get("selected", [])
        st.dataframe([{
            "施設名": c.get("name", ""), "所在地（公開データ）": c.get("address") or "未確認",
            "公式サイト候補（未確認）": c.get("official_url") or "未確認",
            "AI選定理由": c.get("reason", ""), "出典": c.get("source_url", ""),
            "写真候補件数": len(c.get("photos", [])),
        } for c in rows], hide_index=True, width="stretch")
        for c in rows:
            if c.get("photos"):
                with st.expander(f"写真候補：{c.get('name', '')}"):
                    st.dataframe([{
                        "写真候補ページ": p.get("url", ""),
                        "権利者表記": p.get("owner", ""),
                        "掲載ライセンス表示": p.get("license", ""),
                        "利用状況": "未確認（商用SNS投稿の使用許可ではありません）",
                    } for p in c["photos"]], hide_index=True, width="stretch")
        if not draft["imported_at"]:
            accepted = st.checkbox("5件を『未確認の施設候補』として保存することを了承します。公開・画像利用はまだ行いません。",
                                   key=f"ai_import_agree_{draft['id']}")
            if st.button("AI候補5件を施設管理に登録", key=f"ai_import_{draft['id']}",
                         disabled=not accepted):
                try:
                    count = research.import_ai_draft(draft["id"])
                    st.session_state["notice"] = f"AI調査候補を{count}件登録しました。各項目と写真の許諾を確認してください。"
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))
        else:
            st.info("このAI調査案の候補は施設管理へ登録済みです。")
    with st.expander("新しくAIで施設・写真候補を探す"):
        st.caption("無料の公開検索サービスを1回ずつ利用し、Gemini 3.5 Flash-Liteで5件を選びます。"
                   "住所・施設URLはOpenStreetMapの登録情報から取得します。")
        epoch_key = f"_auto_research_epoch_{theme_id}"
        epoch = st.session_state.get(epoch_key, 0)
        with st.form(f"ai_research_form_{theme_id}"):
            area = st.text_input("検索地域（例：大阪市・京都市）", max_chars=65, key=f"ai_area_{theme_id}")
            kind_default = 1 if any(w in theme["title"] for w in ("レストラン", "カフェ", "グルメ", "食事")) else 0
            kind = st.selectbox("施設の種類", ("ホテル", "飲食店"), index=kind_default)
            public_ok = st.checkbox("検索地域をOpenStreetMapへ送り、施設名をWikimedia Commonsへ送ることを承認します",
                                    key=f"ai_public_{theme_id}_{epoch}")
            free_ok = st.checkbox("Google公式料金表でGemini 3.5 Flash-Liteの無料枠を確認しました",
                                  key=f"ai_free_{theme_id}_{epoch}")
            billing_ok = st.checkbox("今回使用するAPIキーはFree tierプロジェクトのもので、Cloud Billingが無効と確認しました",
                                     key=f"ai_billing_{theme_id}_{epoch}")
            send_ok = st.checkbox("AIへテーマ名と公開施設候補を今回1回送信することを承認します（自動再試行なし）",
                                  key=f"ai_google_{theme_id}_{epoch}")
            submitted = st.form_submit_button("公開データを調査してAIで5件選ぶ", type="primary")
        if submitted:
            st.session_state[epoch_key] = epoch + 1  # Each attempt needs fresh consent.
            try:
                if not public_ok:
                    raise AIResearchError("公開データの検索には事前承認が必要です。送信していません。")
                consent = GeminiConsent(free_ok, billing_ok, send_ok)
                consent.validate()  # No network or secret read before consent.
                if not area.strip():
                    raise AIResearchError("調査地域を入力してください。")
                result = build_research(theme["title"], area.strip(), kind, load_api_key(), consent)
                research.save_ai_draft(theme_id, result)
                st.session_state["notice"] = "AI調査が完了しました。5施設と写真候補を『未確認の下書き』に保存しました。"
                st.rerun()
            except ValueError as error:
                st.error(str(error))
