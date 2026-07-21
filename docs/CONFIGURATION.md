<!-- generated-by: gsd-doc-writer -->
# Configuration

Vici uses [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) for configuration management. All settings are defined in `src/config.py`. Each domain has its own sub-settings model (`SmsSettings`, `ExtractionSettings`, `PineconeSettings`, `ObservabilitySettings`, `TemporalSettings`) that reads its env vars directly via `validation_alias` — every value has exactly one home, and code always reads the nested form (`get_settings().sms.auth_token`).

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
| `SMS_RATE_LIMIT_MAX` | No | `5` | Max messages per sender per window, enforced by the webhook rate-limit gate |
| `SMS_RATE_LIMIT_WINDOW_SECONDS` | No | `60` | SMS rate-limit rolling-window size in seconds, enforced by the webhook rate-limit gate |
| `PHONE_HASH_PEPPER` | Prod only | `""` | Secret HMAC key for phone-number pseudonymization. Required when `ENV=production`; an empty value degrades to an unkeyed hash for local development |
| `GPT_MODEL` | No | `"gpt-5.3-chat-latest"` | OpenAI model used for classification/extraction |
| `DISABLE_TWILIO_SIGNATURE_VALIDATION` | No | `false` | Explicit opt-out of webhook signature validation (local development only) |

The Grafana container reads `GF_SECURITY_ADMIN_USER`/`GF_SECURITY_ADMIN_PASSWORD` from `.env.grafana`; those variables are not part of the app's `Settings`.

## Config File Format

There is no standalone config file. All configuration is driven by environment variables loaded via pydantic-settings. The `Settings` class in `src/config.py` accepts an optional `.env` file at the project root:

```python
model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)
```

Variable names are case-insensitive (pydantic-settings default). Any extra variables not declared on a model are silently ignored.

Each sub-settings model reads its own env vars via per-field `validation_alias` (e.g. `SmsSettings.auth_token` ← `TWILIO_AUTH_TOKEN`), so there are no flat duplicates on `Settings`. Downstream code reads structured settings through `get_settings().sms`, `.extraction`, `.pinecone`, `.observability`, and `.temporal`. Only `database_url`, `webhook_base_url`, and `env` remain top-level (they are genuinely global).

## Required vs Optional Settings

The following variables cause a `ValueError` at startup if they are missing or empty. This validation runs inside `Settings._validate_required_credentials` in `src/config.py`:

- `DATABASE_URL`
- `TWILIO_AUTH_TOKEN`
- `OPENAI_API_KEY`
- `PINECONE_API_KEY`
- `TEMPORAL_ADDRESS`
- `WEBHOOK_BASE_URL`
- `ENV`
- `PHONE_HASH_PEPPER` (only when `ENV=production`)

Failure produces an error of the form: `Required credentials are missing or empty: <comma-separated names>`.

All other variables have defaults on `Settings` and are optional from the config layer's point of view. Note that some of these (e.g. `PINECONE_INDEX_HOST`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `BRAINTRUST_API_KEY`, `TWILIO_ACCOUNT_SID`, `TWILIO_FROM_NUMBER`) are documented as **required** by the README (`.env.app` table) because the associated features will not function without them, even though `Settings` does not validate them.

## Defaults

| Field | Default |
|---|---|
| `SmsSettings.rate_limit_max` | `5` |
| `SmsSettings.rate_limit_window_seconds` | `60` |
| `SmsSettings.phone_hash_pepper` | `""` (required in production) |
| `ExtractionSettings.gpt_model` | `"gpt-5.3-chat-latest"` (from `_DEFAULT_GPT_MODEL` in `src/extraction/constants.py`) |
| `ObservabilitySettings.otel_service_name` | `"vici"` |
| `ObservabilitySettings.service_version` | `"dev"` (from `GIT_SHA`) |
| `TemporalSettings.task_queue` | `"vici-queue"` |
| `TemporalSettings.cron_schedule_pinecone_sync` | `"*/5 * * * *"` |

## Per-Environment Overrides

Vici uses separate `.env.*` files for docker-compose services, each scoped to a single container. Copy the corresponding `.env.*.example` file at the project root and fill in values marked `your_*`. The mapping between compose service and env file is defined in `docker-compose.yml`:

| File | Service (docker-compose.yml) | Example file |
|---|---|---|
| `.env.app` | `app` (FastAPI application) | `.env.app.example` |
| `.env.postgres` | `postgres` (PostgreSQL database) | `.env.postgres.example` |
| `.env.opensearch` | `opensearch` (Jaeger storage backend) | `.env.opensearch.example` |
| `.env.jaeger-query` | `jaeger-query` (Jaeger query service) | `.env.jaeger-query.example` |
| `.env.temporal` | `temporal` (Temporal server) | `.env.temporal.example` |
| `.env.temporal-ui` | `temporal-ui` (Temporal UI) | `.env.temporal-ui.example` |
| `.env.grafana` | `grafana` (Grafana dashboard) | `.env.grafana.example` |

Note that the `jaeger-collector`, `prometheus`, and `app`-adjacent `prometheus` services in `docker-compose.yml` do **not** declare an `env_file` and are configured entirely via mounted config files (`jaeger/collector-config.yaml`, `prometheus/prometheus.yml`).

See the "Environment Variables" section of the project [README](../README.md#environment-variables) for the per-file variable lists.

For production on GKE, environment variables are managed via **GCP Secret Manager** and synced into Kubernetes `Secret` resources by the External Secrets Operator (ESO). The Pulumi wiring lives in `infra/components/secrets.py` and is consumed by `infra/components/app.py`. See [DEPLOYMENT.md](DEPLOYMENT.md) for the full secrets pipeline. <!-- VERIFY: exact GCP project IDs, Secret Manager resource names, and ESO `SecretStore`/`ClusterSecretStore` identifiers used in each deployed environment -->

The `ENV` variable controls the runtime environment name. Set it to `development` (or `local`) for local development and `production` for production deployments on GKE.
