"""Opt-in Phase 4.2 editor; no key read on display and no persistent AI drafts."""
import json

import streamlit as st

from studio.ai_copy import (BODY_LIMIT, CAPTION_LIMIT, TITLE_LIMIT, _digest,
                            generate_copy, prepare_copy, review_copy)
from studio.gemini import GeminiConsent
from studio.gemini_models import available_models, model_profile
from studio.research import ResearchStore


def ai_copy_panel(store, theme_id, facility_ids):
    """Return a currently reviewed copy, or None. Offline export remains separate."""
    if not st.checkbox("AIコピー案を作成・編集する（任意）", key=f"copy_enabled_{theme_id}"):
        return None
    st.markdown("**7ページ原稿・TikTokキャプション案（Phase 4.2）**")
    st.caption("生成はGoogleへの外部送信です。1操作1リクエスト、120秒、自動再試行・モデル自動切替・検索なし。"
               "写真・許諾資料は送信せず、許諾状態も変更しません。原稿はこのブラウザセッションのメモリだけに保持します。")
    st.info("未確認の施設情報は文章にしません。AIは中立的な文と、今回あなたが公式情報として確認した短い事実を選びます。"
            "出典を選ばなければ事実を含まない候補紹介です。写真の使用許可や公開承認とは別の確認です。")
    research = ResearchStore(store)
    names = {f["id"]: f["name"] for f in research.facilities(theme_id)}
    sources = {s["id"]: {**s, "facility_name": names[fid]}
               for fid in facility_ids for s in research.sources(fid)}
    source_ids = st.multiselect(
        "今回、公式サイトで内容を確認した出典（任意・選択は本人の確認表明）",
        list(sources), default=[], key=f"copy_sources_{theme_id}",
        format_func=lambda sid: f"{sources[sid]['facility_name']}｜{sources[sid]['label']}｜{sources[sid]['fact']}")
    st.caption("公式サイトと同じホスト・今日以前の確認日・50文字以内の事実に限ります。OSM登録情報は公式確認になりません。"
               "長い説明は施設の出典管理で短い事実として整理してください。")
    try:
        context = prepare_copy(store, theme_id, facility_ids, source_ids)
    except ValueError as error:
        st.error(str(error))
        return None
    models = available_models()
    if not models:
        st.warning("公式確認済みの無料モデルがありません。オフラインZIPを利用してください。")
        return None
    model = st.selectbox("コピー生成モデル（自動切替なし）", models, key=f"copy_model_{theme_id}")
    st.caption(f"Thinking：{model_profile(model).thinking_level}。3.5 Flash-Liteも手動選択できます。無料枠は利用前に再確認してください。")
    with st.expander("送信する施設情報を確認"):
        st.json(context.payload)
        st.caption("この情報と、画面の文字数制約・中立的な文／キャプション／タグの定型選択肢を送ります。"
                   "施設メモ・住所・未確認の料金・写真・許諾資料は送信しません。")
    epoch_key = f"copy_epoch_{theme_id}"
    epoch = st.session_state.get(epoch_key, 0)
    consent_id = f"{theme_id}_{_digest([context.snapshot, context.source_ids, model])}_{epoch}"
    error_key = f"copy_error_{theme_id}"
    if st.session_state.get(error_key):
        st.error(st.session_state[error_key])
    with st.form(f"copy_generate_{consent_id}"):
        free = st.checkbox("Google公式料金表で選択モデルの無料枠を確認しました", key=f"copy_free_{consent_id}")
        billing = st.checkbox("今回のAPIキーのプロジェクトがFree tierでCloud Billing無効と確認しました", key=f"copy_billing_{consent_id}")
        send = st.checkbox("送信する施設情報を確認し、Googleへ今回1回送ることを承認します", key=f"copy_send_{consent_id}")
        submitted = st.form_submit_button("AIでコピー案を作成")
    draft_key = f"copy_draft_{theme_id}"
    reviewed_key = f"copy_reviewed_{theme_id}"
    editor_key = f"copy_editor_{theme_id}"
    if submitted:
        st.session_state[epoch_key] = epoch + 1
        try:
            # generate_copy validates all three confirmations BEFORE loading a key.
            draft = generate_copy(store, context, consent=GeminiConsent(free, billing, send), model=model)
            st.session_state[draft_key] = draft
            st.session_state.pop(reviewed_key, None)
            st.session_state.pop(editor_key, None)
            st.session_state.pop(error_key, None)
        except ValueError as error:
            st.session_state[error_key] = str(error)
        st.rerun()  # Fresh, unchecked consent for every attempt, including failures.
    draft = st.session_state.get(draft_key)
    if draft is None:
        return None
    st.caption(f"生成元：{draft.model} / 生成日時（UTC）：{draft.generated_at} / AI案・公開未承認")
    if draft.context != context:
        st.warning("テーマ・選択施設／順番・出典が変更されています。以前の原稿は書き出せません。送信内容を再確認し、再生成してください。")
        with st.expander("以前の原稿を確認（閲覧専用）"):
            st.json(draft.content)
        return None
    content = st.session_state.get(editor_key, draft.content)
    # Work on a fresh JSON value, leaving the stored original AI draft immutable.
    content = json.loads(json.dumps(content, ensure_ascii=False))
    edit_id = f"{theme_id}_{_digest([draft.generated_at, draft.content_json])}"
    st.write(f"7ページを編集・確認してください。見出し{TITLE_LIMIT}文字、本文{BODY_LIMIT}文字、"
             f"キャプション{CAPTION_LIMIT}文字まで。超過時は切り詰めず拒否します。テンプレート上の収まりは別途確認してください。")
    for page in content["pages"]:
        n = page["page"]
        with st.expander(f"原稿 {n}ページ", expanded=False):
            page["title"] = st.text_input(f"{n}ページの見出し", page["title"], key=f"copy_title_{edit_id}_{n}")
            page["body"] = st.text_area(f"{n}ページの本文", page["body"], key=f"copy_body_{edit_id}_{n}")
            st.caption(f"{len(page['title'])}/{TITLE_LIMIT}文字・{len(page['body'])}/{BODY_LIMIT}文字。出典ID：{page['source_ids'] or '事実の記載なし'}")
    content["caption"] = st.text_area("TikTokキャプション案", content["caption"], key=f"copy_caption_{edit_id}")
    tags = st.text_input("ハッシュタグ案（半角空白で区切る・1〜8件）", " ".join(content["hashtags"]), key=f"copy_tags_{edit_id}")
    content["hashtags"] = tags.split()
    st.session_state[editor_key] = content
    review_id = _digest([context.snapshot, content])
    checked = st.checkbox("7ページ・キャプション・出典と事実を確認しました。編集で加えた事実も公式情報で確認済みです（公開承認ではありません）",
                          key=f"copy_review_agree_{edit_id}_{review_id}")
    reviewed = st.session_state.get(reviewed_key)
    if reviewed is not None and (reviewed.content != content or not checked):
        st.session_state.pop(reviewed_key, None)
        reviewed = None
    if st.button("編集した原稿を確認済みにする", key=f"copy_review_{theme_id}"):
        try:
            reviewed = review_copy(store, draft, content, approved=checked)
            st.session_state[reviewed_key] = reviewed
            st.success("この内容を確認済みにしました。ZIPへの追加を明示選択してください。DB保存・Canva編集・投稿は行っていません。")
        except ValueError as error:
            st.error(str(error))
            return None
    return reviewed
