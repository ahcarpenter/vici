from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.extraction.constants import GPT_MODEL as _DEFAULT_GPT_MODEL

# Every sub-settings model reads its own env vars (via validation_alias) so each
# value has exactly one home — no flat/nested double representation.
_ENV_CONFIG = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)


class SmsSettings(BaseSettings):
    model_config = _ENV_CONFIG

    auth_token: str = Field(default="", validation_alias="TWILIO_AUTH_TOKEN")
    account_sid: str = Field(default="", validation_alias="TWILIO_ACCOUNT_SID")
    from_number: str = Field(default="", validation_alias="TWILIO_FROM_NUMBER")
    rate_limit_max: int = Field(default=5, validation_alias="SMS_RATE_LIMIT_MAX")
    rate_limit_window_seconds: int = Field(
        default=60, validation_alias="SMS_RATE_LIMIT_WINDOW_SECONDS"
    )
    # Secret key for HMAC phone pseudonymization. Required in production —
    # unsalted hashes of the small E.164 space are trivially reversible.
    phone_hash_pepper: str = Field(default="", validation_alias="PHONE_HASH_PEPPER")
    # Explicit opt-in escape hatch — never key on env name
    disable_twilio_signature_validation: bool = Field(
        default=False, validation_alias="DISABLE_TWILIO_SIGNATURE_VALIDATION"
    )


class ExtractionSettings(BaseSettings):
    model_config = _ENV_CONFIG

    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    gpt_model: str = Field(default=_DEFAULT_GPT_MODEL, validation_alias="GPT_MODEL")


class PineconeSettings(BaseSettings):
    model_config = _ENV_CONFIG

    api_key: str = Field(default="", validation_alias="PINECONE_API_KEY")
    index_host: str = Field(default="", validation_alias="PINECONE_INDEX_HOST")


class ObservabilitySettings(BaseSettings):
    model_config = _ENV_CONFIG

    braintrust_api_key: str = Field(default="", validation_alias="BRAINTRUST_API_KEY")
    otel_endpoint: str = Field(
        default="", validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    otel_service_name: str = Field(default="vici", validation_alias="OTEL_SERVICE_NAME")
    service_version: str = Field(default="dev", validation_alias="GIT_SHA")


class TemporalSettings(BaseSettings):
    model_config = _ENV_CONFIG

    address: str = Field(default="", validation_alias="TEMPORAL_ADDRESS")
    task_queue: str = Field(
        default="vici-queue", validation_alias="TEMPORAL_TASK_QUEUE"
    )
    cron_schedule_pinecone_sync: str = Field(
        default="*/5 * * * *", validation_alias="CRON_SCHEDULE_PINECONE_SYNC"
    )


class Settings(BaseSettings):
    model_config = _ENV_CONFIG

    database_url: str = ""
    webhook_base_url: str = ""
    env: str = ""

    sms: SmsSettings = Field(default_factory=SmsSettings)
    extraction: ExtractionSettings = Field(default_factory=ExtractionSettings)
    pinecone: PineconeSettings = Field(default_factory=PineconeSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    temporal: TemporalSettings = Field(default_factory=TemporalSettings)

    @model_validator(mode="after")
    def _validate_required_credentials(self) -> "Settings":
        """Fail fast at startup if required credentials are empty."""
        missing = []
        if not self.database_url:
            missing.append("DATABASE_URL")
        if not self.sms.auth_token:
            missing.append("TWILIO_AUTH_TOKEN")
        if not self.extraction.openai_api_key:
            missing.append("OPENAI_API_KEY")
        if not self.pinecone.api_key:
            missing.append("PINECONE_API_KEY")
        if not self.temporal.address:
            missing.append("TEMPORAL_ADDRESS")
        if not self.webhook_base_url:
            missing.append("WEBHOOK_BASE_URL")
        if not self.env:
            missing.append("ENV")
        if self.env == "production" and not self.sms.phone_hash_pepper:
            missing.append("PHONE_HASH_PEPPER")
        if missing:
            raise ValueError(
                f"Required credentials are missing or empty: {', '.join(missing)}"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # Lazily constructed so importing modules doesn't require env vars.
    return Settings()
