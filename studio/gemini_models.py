"""Model settings enter this registry only after a current official review.

No model has been verified: all five official pages were blocked on 2026-11-08.
This file is maintained in source, never loaded from secrets or environment
variables. Test fixtures use synthetic review records, not real eligibility.
"""
from dataclasses import dataclass
from datetime import date

SDK_VERSION = "3.0.0"
OFFICIAL_DOCS = tuple("https://ai.google.dev/gemini-api/docs/" + page for page in
                      ("models", "pricing", "thinking", "structured-output", "rate-limits"))
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


# Add an entry only after confirming the exact official ID, current availability,
# new free-project eligibility, free text I/O, JSON support and model-specific
# thinking/token settings. An API-key/project check alone does not establish this.
VERIFIED_FREE_MODELS: dict[str, ModelProfile] = {}


def model_profile(model=None):
    if model is None:
        if not VERIFIED_FREE_MODELS:
            raise GeminiError(NO_VERIFIED_MODELS)
        model = next(iter(VERIFIED_FREE_MODELS))
    if not isinstance(model, str):
        raise GeminiError("モデルIDの形式が不正です。送信していません。")
    profile = VERIFIED_FREE_MODELS.get(model)
    if profile is None:
        raise GeminiError("このモデルは利用対象外です。公式確認済みの無料モデル以外へ切り替えません。")
    if (not isinstance(profile, ModelProfile) or profile.model_id != model
        or type(profile.max_output_tokens) is not int or profile.max_output_tokens <= 0
        or type(profile.reviewed_on) is not date or not isinstance(profile.source_urls, tuple)
        or any(not isinstance(url, str) for url in profile.source_urls)
        or not set(OFFICIAL_DOCS).issubset(profile.source_urls)
        or profile.sdk_version != SDK_VERSION
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
