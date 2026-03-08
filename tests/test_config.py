"""
Tests for nested Pydantic Settings (RED until Task 2 implements nested Settings).
"""
import pytest
from pydantic import ValidationError


def test_sms_auth_token_reads_from_twilio_auth_token(monkeypatch):
    """Settings.sms.auth_token should be populated from TWILIO_AUTH_TOKEN env var."""
    from src.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-token-123")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC_test")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

    settings = get_settings()
    assert settings.sms.auth_token == "test-token-123"

    get_settings.cache_clear()


def test_nested_settings_has_four_sub_models():
    """Settings must expose sms, extraction, pinecone, and observability sub-models."""
    from src.config import get_settings

    settings = get_settings()
    assert hasattr(settings, "sms"), "Settings missing .sms sub-model"
    assert hasattr(settings, "extraction"), "Settings missing .extraction sub-model"
    assert hasattr(settings, "pinecone"), "Settings missing .pinecone sub-model"
    assert hasattr(settings, "observability"), "Settings missing .observability sub-model"


def test_extraction_gpt_model_default():
    """Settings.extraction.gpt_model should default to 'gpt-4o'."""
    from src.config import get_settings

    settings = get_settings()
    assert settings.extraction.gpt_model == "gpt-4o"
