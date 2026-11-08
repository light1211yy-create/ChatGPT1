"""Synthetic model reviews for transport/UI mocks, never real API eligibility."""
from datetime import date

import pytest

from studio import gemini_models


@pytest.fixture
def mock_reviewed_models(monkeypatch):
    profiles = {model: gemini_models.ModelProfile(
        model_id=model, max_output_tokens=8192, thinking_budget=0, thinking_level=None,
        reviewed_on=date(2026, 11, 8), source_urls=gemini_models.OFFICIAL_DOCS,
    ) for model in ("gemini-2.5-flash-lite", "gemini-2.5-flash")}
    monkeypatch.setattr(gemini_models, "VERIFIED_FREE_MODELS", profiles)
    return profiles
