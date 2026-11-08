"""Explicit Gemini opt-in and one-request consent, with no stored API keys."""
import os

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from studio.gemini import PRICING_URL
from studio.gemini_models import NO_VERIFIED_MODELS, available_models

GEMINI_MODE = "Gemini AIモード"
TEST_MODE = "無料テストモード（従来方式）"


def read_api_key():
    key = os.environ.get("GEMINI_API_KEY", "")
    if key:
        return key
    try:
        key = st.secrets.get("GEMINI_API_KEY", "")
    except (StreamlitSecretNotFoundError, FileNotFoundError, KeyError):
        return ""
    return key if isinstance(key, str) else ""


def choose_mode():
    mode = st.radio("生成モード", (GEMINI_MODE, TEST_MODE), index=1, key="generation_mode")
    if mode == TEST_MODE:
        st.info("無料テストモード：AIモデルには接続していません。ルールベースで10案を作成し、追加課金や外部へのデータ送信は発生しません。")
        return mode, None
    st.warning("Gemini AIモードはGoogleへの外部送信を伴います。Google AI Pro・Antigravityの契約とGemini API課金は別です。")
    st.write("送信対象：企画対象日・重点ジャンル・企画メモ、ジャンル別の投稿実績集計、直近300件までのテーマ名。投稿実績の個別タイトル・写真権利資料・DB全体は送信対象外です。")
    st.caption("企画メモ・テーマ名に秘密情報や個人情報を入力しないでください。共通パターンの検出だけで、すべての個人情報を自動判定できるわけではありません。")
    st.markdown(f"[公式料金表を確認]({PRICING_URL})")
    st.info("キーのプロジェクト別の無料枠は未確認です。公式確認済みモデルでも、本人によるFree tier・Cloud Billing無効の確認と今回1回の送信承認が必要です。アプリから課金状態は検証できません。")
    models = available_models()
    model = st.selectbox("Geminiモデル（公式確認済みの無料モデルのみ）", models, disabled=not models)
    if not models:
        st.error(NO_VERIFIED_MODELS)
        st.caption("2026-11-08：公式資料5ページは環境プロキシで403となりました。3.5の正式ID・無料枠・設定と、旧2.5の現在の利用資格は未確認です。")
        return mode, None
    if not read_api_key():
        st.warning("GEMINI_API_KEYが未設定です。キーは画面に貼り付けず、環境変数またはGit管理外の秘密設定を使用してください。")
    return mode, model
