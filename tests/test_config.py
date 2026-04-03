"""
Tests for nested Pydantic Settings (RED until Task 2 implements nested Settings).
"""


def test_sms_auth_token_reads_from_twilio_auth_token(monkeypatch):
    """Settings.sms.auth_token should be populated from TWILIO_AUTH_TOKEN env var."""
    from src.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-token-123")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC_test")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("PINECONE_API_KEY", "pc-test")

    settings = get_settings()
    assert settings.sms.auth_token == "test-token-123"

    get_settings.cache_clear()


def test_nested_settings_has_four_sub_models(monkeypatch):
    """Settings must expose sms, extraction, pinecone, and observability sub-models."""
    from src.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("PINECONE_API_KEY", "pc-test")

    settings = get_settings()
    assert hasattr(settings, "sms"), "Settings missing .sms sub-model"
    assert hasattr(settings, "extraction"), "Settings missing .extraction sub-model"
    assert hasattr(settings, "pinecone"), "Settings missing .pinecone sub-model"
    assert hasattr(settings, "observability"), "Settings missing .observability sub-model"

    get_settings.cache_clear()


def test_extraction_gpt_model_default(monkeypatch):
    """Settings.extraction.gpt_model should default to 'gpt-5.3-chat-latest'."""
    from src.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("PINECONE_API_KEY", "pc-test")

    settings = get_settings()
    assert settings.extraction.gpt_model == "gpt-5.3-chat-latest"

    get_settings.cache_clear()


def test_config_raises_on_empty_database_url(monkeypatch):
    """Settings raises ValueError when DATABASE_URL is empty."""
    import pytest
    from src.config import get_settings, Settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("PINECONE_API_KEY", "pc-test")

    with pytest.raises(Exception) as exc_info:
        Settings()
    assert "database_url" in str(exc_info.value).lower()

    get_settings.cache_clear()


def test_config_raises_on_empty_openai_api_key(monkeypatch):
    """Settings raises ValueError when OPENAI_API_KEY is empty."""
    import pytest
    from src.config import Settings

    with pytest.raises(Exception):
        Settings(
            database_url="sqlite+aiosqlite:///:memory:",
            twilio_auth_token="tok",
            openai_api_key="",
            pinecone_api_key="pc-test",
        )


def test_config_raises_on_empty_twilio_auth_token(monkeypatch):
    """Settings raises ValueError when TWILIO_AUTH_TOKEN is empty."""
    import pytest
    from src.config import Settings

    with pytest.raises(Exception):
        Settings(
            database_url="sqlite+aiosqlite:///:memory:",
            twilio_auth_token="",
            openai_api_key="sk-test",
            pinecone_api_key="pc-test",
        )


def test_config_raises_on_empty_pinecone_api_key(monkeypatch):
    """Settings raises ValueError when PINECONE_API_KEY is empty."""
    import pytest
    from src.config import Settings

    with pytest.raises(Exception):
        Settings(
            database_url="sqlite+aiosqlite:///:memory:",
            twilio_auth_token="tok",
            openai_api_key="sk-test",
            pinecone_api_key="",
        )


def test_config_valid_when_all_credentials_present():
    """Settings constructs without error when all four required credentials are provided."""
    from src.config import Settings

    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        twilio_auth_token="tok",
        openai_api_key="sk-test",
        pinecone_api_key="pc-test",
    )
    assert s.database_url == "sqlite+aiosqlite:///:memory:"
