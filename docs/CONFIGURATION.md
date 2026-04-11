<!-- generated-by: gsd-doc-writer -->
# Configuration

Vici uses [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) for configuration management. All settings are defined in `src/config.py` as a single `Settings` class that reads environment variables (or a `.env` file) and remaps flat env vars into nested sub-models for each domain.

## Environment Variables

The following variables are read by `src/config.py`. Variables documented in the `.env.*.example` files but not bound to a field on `Settings` are silently ignored at runtime (`extra="ignore"`).

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | Yes | — | Async SQLAlchemy connection string for PostgreSQL (e.g. `postgresql+asyncpg://...`) |
| `WEBHOOK_BASE_URL` | Yes | — | Public base URL for inbound Twilio webhooks |
| `ENV` | Yes | — | Runtime environment name (e.g. `local`, `development`, `production`) |
| `TEMPORAL_ADDRESS` | Yes | — | Temporal frontend address (e.g. `temporal:7233`) |
| `TWILIO_AUTH_TOKEN` | Yes | — | Twilio API auth token; also used to validate inbound webhook signatures |
| `TWILIO_ACCOUNT_SID` | No | `""` | Twilio account SID |
| `TWILIO_FROM_NUMBER` | No | `""` | Twilio sender phone number for outbound SMS |
| `OPENAI_API_KEY` | Yes | — | OpenAI API key used for GPT classification and embeddings |
| `PINECONE_API_KEY` | Yes | — | Pinecone vector database API key |
| `PINECONE_INDEX_HOST` | No | `""` | Pinecone index host URL |
| `TEMPORAL_TASK_QUEUE` | No | `"vici-queue"` | Temporal task queue name |
| `CRON_SCHEDULE_PINECONE_SYNC` | No | `"*/5 * * * *"` | Cron expression for the Pinecone sync schedule |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | No | `""` | OpenTelemetry collector OTLP endpoint |
| `OTEL_SERVICE_NAME` | No | `"vici"` | OpenTelemetry service name reported in traces |
| `BRAINTRUST_API_KEY` | No | `""` | Braintrust observability API key |
| `GIT_SHA` | No | `"dev"` | Git commit SHA used as `service.version` in telemetry; set by CI in production |
| `SMS_RATE_LIMIT_WINDOW_SECONDS` | No | `60` | SMS rate-limit sliding-window size in seconds (bound to `Settings.sms_rate_limit_window_seconds`; note: the enforced rate-limit values used at runtime live in `src/sms/constants.py`) |
| `GRAFANA_ADMIN_USER` | No | `"admin"` | Grafana admin username (used by docker-compose) |
| `GRAFANA_ADMIN_PASSWORD` | No | `"admin"` | Grafana admin password (used by docker-compose) |

> **Note:** `SMS_RATE_LIMIT_MAX` is documented in the README but is not bound to any field on `Settings` in `src/config.py`. The effective rate-limit max is the compile-time constant `MAX_MESSAGES_PER_WINDOW = 5` in `src/sms/constants.py`, and the effective window is `RATE_LIMIT_WINDOW_SECONDS = 60` in the same file. The `sms_rate_limit_window_seconds` setting is currently a wiring hook that is not read by the SMS rate-limiter.

## Config File Format

There is no standalone config file. All configuration is driven by environment variables loaded via pydantic-settings. The `Settings` class in `src/config.py` accepts an optional `.env` file at the project root:

```python
model_config = SettingsConfigDict(env_file=".env", extra="ignore")
```

Variable names are case-insensitive (pydantic-settings default). Any extra variables not declared on the model are silently ignored.

Because flat env vars are remapped into nested sub-models via a `model_validator(mode="after")`, downstream code should read structured settings through `get_settings().sms`, `.extraction`, `.pinecone`, `.observability`, and `.temporal` rather than reading the flat top-level fields directly.

## Required vs Optional Settings

The following variables cause a `ValueError` at startup if they are missing or empty. This validation runs inside `Settings._validate_required_credentials` (`src/config.py` lines 87–109):

- `DATABASE_URL`
- `TWILIO_AUTH_TOKEN`
- `OPENAI_API_KEY`
- `PINECONE_API_KEY`
- `TEMPORAL_ADDRESS`
- `WEBHOOK_BASE_URL`
- `ENV`

Failure produces an error of the form: `Required credentials are missing or empty: <comma-separated names>`.

All other variables have defaults on `Settings` and are optional from the config layer's point of view. Note that some of these (e.g. `PINECONE_INDEX_HOST`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `BRAINTRUST_API_KEY`, `TWILIO_ACCOUNT_SID`, `TWILIO_FROM_NUMBER`) are documented as **required** by the README because the associated features will not function without them, even though `Settings` does not validate them.

## Defaults

| Variable / Field | Default | Source |
|---|---|---|
| `otel_service_name` | `"vici"` | `src/config.py` line 54 |
| `git_sha` | `"dev"` | `src/config.py` line 65 |
| `temporal_task_queue` | `"vici-queue"` | `src/config.py` line 68 |
| `cron_schedule_pinecone_sync` | `"*/5 * * * *"` | `src/config.py` line 69 |
| `sms_rate_limit_window_seconds` | `60` | `src/config.py` line 72 |
| `grafana_admin_user` | `"admin"` | `src/config.py` line 75 |
| `grafana_admin_password` | `"admin"` | `src/config.py` line 76 |
| `SmsSettings.rate_limit_max` (nested) | `5` | `src/config.py` line 13 |
| `SmsSettings.rate_limit_window_seconds` (nested) | `60` | `src/config.py` line 14 |
| `ExtractionSettings.gpt_model` | `"gpt-5.3-chat-latest"` (from `_DEFAULT_GPT_MODEL`) | `src/extraction/constants.py` line 1 |
| `ObservabilitySettings.otel_service_name` (nested) | `"vici"` | `src/config.py` line 30 |
| `ObservabilitySettings.service_version` (nested) | `"dev"` | `src/config.py` line 31 |
| `TemporalSettings.task_queue` (nested) | `"vici-queue"` | `src/config.py` line 36 |
| `TemporalSettings.cron_schedule_pinecone_sync` (nested) | `"*/5 * * * *"` | `src/config.py` line 37 |
| `MAX_MESSAGES_PER_WINDOW` (SMS rate-limit max, enforced at runtime) | `5` | `src/sms/constants.py` line 2 |
| `RATE_LIMIT_WINDOW_SECONDS` (SMS rate-limit window, enforced at runtime) | `60` | `src/sms/constants.py` line 1 |

## Per-Environment Overrides

Vici uses separate `.env.*` files for docker-compose services, each scoped to a single container. Copy the corresponding `.env.*.example` file at the project root and fill in values marked `your_*`:

| File | Service | Example file |
|---|---|---|
| `.env.app` | FastAPI application | `.env.app.example` |
| `.env.postgres` | PostgreSQL database | `.env.postgres.example` |
| `.env.opensearch` | OpenSearch (Jaeger storage backend) | `.env.opensearch.example` |
| `.env.temporal` | Temporal server | `.env.temporal.example` |
| `.env.temporal-ui` | Temporal UI | `.env.temporal-ui.example` |
| `.env.jaeger-query` | Jaeger query service | `.env.jaeger-query.example` |
| `.env.grafana` | Grafana dashboard | `.env.grafana.example` |

See the "Environment Variables" section of the project README for the per-file variable lists (`.env.app`, `.env.postgres`, `.env.temporal`, `.env.temporal-ui`, `.env.opensearch`, `.env.jaeger-query`, `.env.grafana`).

For production on GKE, environment variables are managed via **GCP Secret Manager** and synced into Kubernetes `Secret` resources by the External Secrets Operator (ESO). The Pulumi wiring lives in `infra/components/secrets.py` and is consumed by `infra/components/app.py`. See [DEPLOYMENT.md](DEPLOYMENT.md) for the full secrets pipeline. <!-- VERIFY: exact GCP project, Secret Manager secret names, and ESO `SecretStore`/`ClusterSecretStore` identifiers used in each deployed environment -->

The `ENV` variable controls the runtime environment name. Set it to `development` (or `local`) for local development and `production` for production deployments on GKE.
