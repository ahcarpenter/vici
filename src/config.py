from functools import lru_cache

from pydantic import BaseModel, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SmsSettings(BaseModel):
    auth_token: str = ""
    account_sid: str = ""
    from_number: str = ""
    rate_limit_max: int = 5


class ExtractionSettings(BaseModel):
    openai_api_key: str = ""
    gpt_model: str = "gpt-4o"


class PineconeSettings(BaseModel):
    api_key: str = ""
    index_host: str = ""


class ObservabilitySettings(BaseModel):
    braintrust_api_key: str = ""
    otel_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "vici"


class Settings(BaseSettings):
    # Flat env vars (kept for backward compatibility — populated from env)
    database_url: str = ""
    webhook_base_url: str = "http://localhost:8000"
    env: str = "production"
    inngest_dev: bool = False
    inngest_base_url: str = "http://localhost:8288"

    # Flat Twilio env vars (remapped into sms sub-model)
    twilio_auth_token: str = ""
    twilio_account_sid: str = ""
    twilio_from_number: str = ""

    # Flat observability env vars (remapped into observability sub-model)
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "vici"

    # Flat extraction env vars (remapped into extraction sub-model)
    openai_api_key: str = ""

    # Flat Pinecone env vars (remapped into pinecone sub-model)
    pinecone_api_key: str = ""
    pinecone_index_host: str = ""

    # Flat observability env vars
    braintrust_api_key: str = ""

    # Nested sub-models (populated via model_validator below)
    sms: SmsSettings = SmsSettings()
    extraction: ExtractionSettings = ExtractionSettings()
    pinecone: PineconeSettings = PineconeSettings()
    observability: ObservabilitySettings = ObservabilitySettings()

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def _build_sub_models(self) -> "Settings":
        """Remap flat env var fields into nested sub-models."""
        self.sms = SmsSettings(
            auth_token=self.twilio_auth_token,
            account_sid=self.twilio_account_sid,
            from_number=self.twilio_from_number,
        )
        self.extraction = ExtractionSettings(
            openai_api_key=self.openai_api_key,
        )
        self.pinecone = PineconeSettings(
            api_key=self.pinecone_api_key,
            index_host=self.pinecone_index_host,
        )
        self.observability = ObservabilitySettings(
            braintrust_api_key=self.braintrust_api_key,
            otel_endpoint=self.otel_exporter_otlp_endpoint,
            otel_service_name=self.otel_service_name,
        )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # Lazily constructed so importing modules doesn't require env vars.
    return Settings()
