"""Explicit Gemini opt-in and one-request consent, with no stored API keys."""
import streamlit as st

from studio.gemini import PRICING_URL
from studio.gemini_models import DEFAULT_MODEL_ID, NO_VERIFIED_MODELS, available_models, model_profile
from studio.key_config import load_api_key

GEMINI_MODE = "Gemini AIモード"
TEST_MODE = "無料テストモード（従来方式）"


def read_api_key():
    return load_api_key()


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
    model = st.selectbox("Geminiモデル（公式確認済みの無料モデルのみ）", models,
                         index=models.index(DEFAULT_MODEL_ID) if DEFAULT_MODEL_ID in models else 0, disabled=not models)
    if not models:
        st.error(NO_VERIFIED_MODELS)
        return mode, None
    profile = model_profile(model)
    if profile.confirmation_source == "user_confirmation":
        st.caption(f"{profile.reviewed_on.isoformat()}：ユーザーがGoogle公式資料で確認した情報を根拠に登録しています。Codexによるページ直接取得・実API接続の確認ではありません。")
    st.info("初回の実APIテストは別途承認後に1回だけ実施します。この開発依頼は実通信の承認ではありません。キーが確認済みのFree tierプロジェクトに対応することを初回通信前に再確認してください。")
    st.caption("画面の表示・モード選択ではAPIキーを読み取りません。生成時に3つの確認・承認が揃ってから読み取ります。")
    return mode, model
