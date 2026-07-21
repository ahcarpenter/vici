"""Tests for nested Pydantic Settings — each env var has exactly one home."""

import pytest

from src.config import Settings, get_settings

REQUIRED_ENV = {
    "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
    "TWILIO_AUTH_TOKEN": "test-token-123",
    "TWILIO_ACCOUNT_SID": "AC_test",
    "OPENAI_API_KEY": "sk-test",
    "PINECONE_API_KEY": "pc-test",
    "TEMPORAL_ADDRESS": "localhost:7233",
    "WEBHOOK_BASE_URL": "http://localhost:8000",
    "ENV": "test",
}


@pytest.fixture
def required_env(monkeypatch):
    get_settings.cache_clear()
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    yield monkeypatch
    get_settings.cache_clear()


def test_sms_auth_token_reads_from_twilio_auth_token(required_env):
    """Settings.sms.auth_token should be populated from TWILIO_AUTH_TOKEN env var."""
    settings = Settings()
    assert settings.sms.auth_token == "test-token-123"


def test_nested_settings_sub_models(required_env):
    """Settings must expose sms, extraction, pinecone, observability, temporal."""
    settings = Settings()
    for name in ("sms", "extraction", "pinecone", "observability", "temporal"):
        assert hasattr(settings, name), f"Settings missing .{name} sub-model"


def test_extraction_gpt_model_default(required_env):
    """Settings.extraction.gpt_model should default to 'gpt-5.3-chat-latest'."""
    settings = Settings()
    assert settings.extraction.gpt_model == "gpt-5.3-chat-latest"


def test_rate_limit_settings_read_from_env(required_env):
    """SMS_RATE_LIMIT_MAX / SMS_RATE_LIMIT_WINDOW_SECONDS drive sms sub-model."""
    required_env.setenv("SMS_RATE_LIMIT_MAX", "9")
    required_env.setenv("SMS_RATE_LIMIT_WINDOW_SECONDS", "120")
    settings = Settings()
    assert settings.sms.rate_limit_max == 9
    assert settings.sms.rate_limit_window_seconds == 120


def test_temporal_task_queue_reads_from_env(required_env):
    """TEMPORAL_TASK_QUEUE overrides the default queue name."""
    required_env.setenv("TEMPORAL_TASK_QUEUE", "custom-queue")
    settings = Settings()
    assert settings.temporal.task_queue == "custom-queue"


def test_no_flat_credential_duplicates(required_env):
    """Credentials live only on sub-models — no flat copies on Settings."""
    for flat_name in (
        "twilio_auth_token",
        "openai_api_key",
        "pinecone_api_key",
        "braintrust_api_key",
        "temporal_address",
        "grafana_admin_user",
        "grafana_admin_password",
    ):
        assert flat_name not in Settings.model_fields, (
            f"flat field {flat_name} should not exist on Settings"
        )


@pytest.mark.parametrize(
    "env_var",
    [
        "DATABASE_URL",
        "TWILIO_AUTH_TOKEN",
        "OPENAI_API_KEY",
        "PINECONE_API_KEY",
        "TEMPORAL_ADDRESS",
        "WEBHOOK_BASE_URL",
        "ENV",
    ],
)
def test_config_raises_on_missing_required(required_env, env_var):
    """Settings raises naming the missing env var when a credential is empty."""
    required_env.setenv(env_var, "")
    with pytest.raises(Exception) as exc_info:
        Settings()
    assert env_var.lower() in str(exc_info.value).lower()


def test_phone_hash_pepper_required_in_production(required_env):
    """PHONE_HASH_PEPPER must be set when ENV=production."""
    required_env.setenv("ENV", "production")
    required_env.delenv("PHONE_HASH_PEPPER", raising=False)
    with pytest.raises(Exception) as exc_info:
        Settings()
    assert "phone_hash_pepper" in str(exc_info.value).lower()

    required_env.setenv("PHONE_HASH_PEPPER", "prod-pepper")
    assert Settings().sms.phone_hash_pepper == "prod-pepper"


def test_config_valid_when_all_credentials_present(required_env):
    """Settings constructs when all required credentials are present."""
    s = Settings()
    assert s.database_url == "sqlite+aiosqlite:///:memory:"
