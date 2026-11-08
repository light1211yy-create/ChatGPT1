"""Explicit, consent-gated key loading and local status-only diagnostics.

Never import an API client, print key material, or fall back from a malformed
project file to a different credential. No prefix/length/authentication checks.
"""
from pathlib import Path
import json
import os
import tomllib

from studio.gemini_models import GeminiError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KEY_NAME = "GEMINI_API_KEY"
MISSING_MESSAGE = (
    "GEMINI_API_KEYが未設定です。app.pyと同じフォルダの.streamlit/secrets.tomlの"
    "トップレベル、または環境変数GEMINI_API_KEYに設定してください。"
)


class KeyConfigError(GeminiError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def project_secrets_path():
    return PROJECT_ROOT / ".streamlit" / "secrets.toml"


def normalize_key(value):
    """Transport hygiene only; AQ., AIza, and other prefixes are not judged."""
    if not isinstance(value, str):
        raise KeyConfigError("type", "GEMINI_API_KEYは文字列で設定してください。値は表示していません。")
    value = value.strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise KeyConfigError("control", "GEMINI_API_KEYに改行などの制御文字が含まれています。値は表示していません。")
    return value


def _file_key(path):
    try:
        # Windows editors may save UTF-8 BOM. utf-8-sig also accepts ordinary UTF-8.
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None
    except (tomllib.TOMLDecodeError, UnicodeError):
        raise KeyConfigError("toml", "secrets.tomlの構文またはUTF-8文字コードが不正です。トップレベルのGEMINI_API_KEYを引用符で囲んだ文字列にしてください。") from None
    except OSError:
        raise KeyConfigError("file", "プロジェクトの.streamlit/secrets.tomlを読み取れません。ファイルの場所とアクセス権を確認してください。") from None
    if KEY_NAME not in data:
        raise KeyConfigError("missing_key", "secrets.tomlのトップレベルにGEMINI_API_KEYが未設定です。[gemini]などのセクション内ではなく、セクションより前に設定してください。")
    key = normalize_key(data[KEY_NAME])
    if not key:
        raise KeyConfigError("blank", "secrets.tomlのGEMINI_API_KEYが空文字・空白（未設定）です。別の設定元へ自動切り替えは行いません。")
    return key


def load_api_key():
    """Call only after consent. Project file wins; env only if file is absent."""
    key = _file_key(project_secrets_path())
    if key is not None:
        return key
    key = normalize_key(os.environ.get(KEY_NAME, ""))
    if not key:
        raise KeyConfigError("missing", MISSING_MESSAGE)
    return key


def _path_flag(path, *, file_only=False):
    try:
        return path.is_file() if file_only else path.exists()
    except OSError:
        return None


def configuration_status():
    """User-run local diagnosis: return fixed states, never key data or hashes."""
    path = project_secrets_path()
    file_error = None
    try:
        file_key = _file_key(path)
        file_state = "なし" if file_key is None else "あり・TOML正常・キー設定あり"
    except KeyConfigError as error:
        file_key = None
        file_error = error.code
        file_state = {
            "toml": "あり・TOML構文または文字コードが不正",
            "file": "読取不可",
            "missing_key": "あり・トップレベルのキー項目なし",
            "blank": "あり・キーが空文字または空白",
            "type": "あり・キーが文字列ではない",
            "control": "あり・キーに制御文字あり",
        }[error.code]
    try:
        raw_env = os.environ.get(KEY_NAME)
        env_key = normalize_key(raw_env) if raw_env is not None else ""
        env_state = "設定あり" if env_key else ("未設定" if raw_env is None else "空文字または空白")
    except KeyConfigError:
        env_key = ""
        env_state = "値の設定エラー"
    if file_error:
        source = "なし（ファイル設定エラーで停止）"
    elif file_key is not None:
        source = "プロジェクトの.streamlit/secrets.toml"
    elif env_key:
        source = "環境変数GEMINI_API_KEY"
    else:
        source = "なし"
    app_flag = _path_flag(PROJECT_ROOT / "app.py", file_only=True)
    txt_flag = _path_flag(path.with_suffix(".toml.txt"))
    return {
        "プロジェクト基準": "このモジュールと同じプロジェクトのapp.py",
        "app.py": "確認不可" if app_flag is None else ("あり" if app_flag else "なし"),
        ".streamlit/secrets.toml": file_state,
        ".streamlit/secrets.toml.txt": "確認不可" if txt_flag is None else ("あり（拡張子を確認）" if txt_flag else "なし"),
        "環境変数GEMINI_API_KEY": env_state,
        "使用される設定元": source,
        "優先順位": "プロジェクトのsecrets.toml > 環境変数（ファイルがない場合のみ）",
        "有効性・課金状態": "判定しません",
        "API通信": "行いません",
    }


def print_diagnostics():
    print(json.dumps(configuration_status(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    print_diagnostics()
