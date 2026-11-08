"""Model settings with explicit evidence provenance.

Gemini 3.5 was confirmed by the user against official sources on 2026-11-09;
Codex did not retrieve those pages. This registry is maintained in source, never
loaded from secrets/environment. Test fixtures are not real eligibility.
"""
from dataclasses import dataclass
from datetime import date

SDK_VERSION = "3.0.0"
DOCS_ROOT = "https://ai.google.dev/gemini-api/docs/"
DEFAULT_MODEL_ID = "gemini-3.5-flash-lite"
MODEL_SPEC_URL = DOCS_ROOT + "models/" + DEFAULT_MODEL_ID
PRICING_URL = DOCS_ROOT + "pricing"
THINKING_URL = DOCS_ROOT + "generate-content/thinking"
OFFICIAL_DOCS = (DOCS_ROOT + "models", PRICING_URL, THINKING_URL,
                 DOCS_ROOT + "structured-output", DOCS_ROOT + "rate-limits")
NO_VERIFIED_MODELS = (
    "公式資料で現在の無料枠・新規Free tierの利用資格・モデル設定を確認できたモデルがありません。"
    "Gemini生成は停止しています。無料テストモードをご利用ください。"
)


class GeminiError(ValueError):
    """Only safe Japanese messages may cross the UI boundary."""


@dataclass(frozen=True)
class ModelProfile:
    model_id: str
    max_output_tokens: int
    thinking_budget: int | None
    thinking_level: str | None
    reviewed_on: date
    source_urls: tuple[str, ...]
    sdk_version: str = SDK_VERSION
    confirmation_source: str = "test_fixture"


# The user confirmed the stable ID, Standard Free tier text I/O, structured
# output and supported thinking levels. Project/key eligibility is still a
# separate preflight check. 8192 is our request cap, not a claimed model maximum.
VERIFIED_FREE_MODELS: dict[str, ModelProfile] = {
    DEFAULT_MODEL_ID: ModelProfile(
        model_id=DEFAULT_MODEL_ID, max_output_tokens=8192,
        thinking_budget=None, thinking_level="MINIMAL", reviewed_on=date(2026, 11, 9),
        source_urls=(MODEL_SPEC_URL, PRICING_URL, THINKING_URL),
        confirmation_source="user_confirmation",
    ),
}


def model_profile(model=None):
    if model is None:
        if not VERIFIED_FREE_MODELS:
            raise GeminiError(NO_VERIFIED_MODELS)
        model = DEFAULT_MODEL_ID if DEFAULT_MODEL_ID in VERIFIED_FREE_MODELS else next(iter(VERIFIED_FREE_MODELS))
    if not isinstance(model, str):
        raise GeminiError("モデルIDの形式が不正です。送信していません。")
    profile = VERIFIED_FREE_MODELS.get(model)
    if profile is None:
        raise GeminiError("このモデルは利用対象外です。公式確認済みの無料モデル以外へ切り替えません。")
    if (not isinstance(profile, ModelProfile) or profile.model_id != model
        or type(profile.max_output_tokens) is not int or profile.max_output_tokens <= 0
        or type(profile.reviewed_on) is not date or not isinstance(profile.source_urls, tuple)
        or any(not isinstance(url, str) for url in profile.source_urls)
        or not {PRICING_URL, THINKING_URL}.issubset(profile.source_urls)
        or not ({DOCS_ROOT + "models", DOCS_ROOT + "models/" + model} & set(profile.source_urls))
        or profile.sdk_version != SDK_VERSION
        or profile.confirmation_source not in ("user_confirmation", "developer_review", "test_fixture")
        or (profile.thinking_budget is not None and
            (type(profile.thinking_budget) is not int or profile.thinking_budget < 0))
        or (profile.thinking_level is not None and profile.thinking_level not in ("MINIMAL", "LOW", "MEDIUM", "HIGH"))
        or (profile.thinking_budget is not None and profile.thinking_level is not None)):
        raise GeminiError("モデル別設定・公式確認記録・SDKの組み合わせが不正です。送信せず停止しました。")
    return profile


def available_models():
    models = []
    for model in VERIFIED_FREE_MODELS:
        try:
            model_profile(model)
        except GeminiError:
            continue
        models.append(model)
    return tuple(models)
