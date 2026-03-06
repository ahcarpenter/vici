from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    twilio_auth_token: str
    twilio_account_sid: str
    webhook_base_url: str = "http://localhost:8000"
    inngest_dev: bool = False
    inngest_base_url: str = "http://localhost:8288"
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "vici"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
