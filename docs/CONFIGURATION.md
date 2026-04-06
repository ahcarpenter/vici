<!-- generated-by: gsd-doc-writer -->
# Configuration

Vici uses [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) for configuration management. All settings are defined in `src/config.py` as a single `Settings` class that reads environment variables (or a `.env` file) and remaps flat env vars into nested sub-models for each domain.

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | Yes | — | Async SQLAlchemy connection string for PostgreSQL (e.g. `postgresql+asyncpg://...`) |
| `TWILIO_AUTH_TOKEN` | Yes | — | Twilio API auth token for SMS sending |
| `TWILIO_ACCOUNT_SID` | No | `""` | Twilio account SID |
| `TWILIO_FROM_NUMBER` | No | `""` | Twilio sender phone number |
| `OPENAI_API_KEY` | Yes | — | OpenAI API key for GPT-based extraction |
| `PINECONE_API_KEY` | Yes | — | Pinecone vector database API key |
| `PINECONE_INDEX_HOST` | No | `""` | Pinecone index host URL |
| `TEMPORAL_ADDRESS` | Yes | — | Temporal server address (e.g. `temporal:7233`) |
| `TEMPORAL_TASK_QUEUE` | No | `"vici-queue"` | Temporal task queue name |
| `CRON_SCHEDULE_PINECONE_SYNC` | No | `"*/5 * * * *"` | Cron expression for Pinecone sync schedule |
| `WEBHOOK_BASE_URL` | Yes | — | Base URL for inbound webhook callbacks |
| `ENV` | Yes | — | Environment name (e.g. `local`, `staging`, `production`) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | No | `""` | OpenTelemetry collector OTLP endpoint |
| `OTEL_SERVICE_NAME` | No | `"vici"` | OpenTelemetry service name |
| `BRAINTRUST_API_KEY` | No | `""` | Braintrust observability API key |
| `GIT_SHA` | No | `"dev"` | Git commit SHA used as service version in telemetry |
| `SMS_RATE_LIMIT_WINDOW_SECONDS` | No | `60` | SMS rate-limit sliding window in seconds |
| `GRAFANA_ADMIN_USER` | No | `"admin"` | Grafana admin username (docker-compose only) |
| `GRAFANA_ADMIN_PASSWORD` | No | `"admin"` | Grafana admin password (docker-compose only) |

## Config File Format

There is no standalone config file. All configuration is driven by environment variables loaded via pydantic-settings. The `Settings` class in `src/config.py` accepts an optional `.env` file at the project root:

```python
model_config = SettingsConfigDict(env_file=".env", extra="ignore")
```

Variable names are case-insensitive (pydantic-settings default). Any extra variables not declared on the model are silently ignored.

## Required vs Optional Settings

The following variables cause a `ValueError` at startup if they are missing or empty. This validation runs inside `Settings._validate_required_credentials`:

- `DATABASE_URL`
- `TWILIO_AUTH_TOKEN`
- `OPENAI_API_KEY`
- `PINECONE_API_KEY`
- `TEMPORAL_ADDRESS`
- `WEBHOOK_BASE_URL`
- `ENV`

All other variables have defaults and are optional.

## Defaults

| Variable | Default | Source |
|---|---|---|
| `TEMPORAL_TASK_QUEUE` | `"vici-queue"` | `src/config.py` line 68 |
| `CRON_SCHEDULE_PINECONE_SYNC` | `"*/5 * * * *"` | `src/config.py` line 69 |
| `OTEL_SERVICE_NAME` | `"vici"` | `src/config.py` line 54 |
| `GIT_SHA` | `"dev"` | `src/config.py` line 65 |
| `SMS_RATE_LIMIT_WINDOW_SECONDS` | `60` | `src/config.py` line 73 |
| `GRAFANA_ADMIN_USER` | `"admin"` | `src/config.py` line 75 |
| `GRAFANA_ADMIN_PASSWORD` | `"admin"` | `src/config.py` line 76 |
| `GPT_MODEL` (extraction) | `"gpt-5.3-chat-latest"` | `src/extraction/constants.py` |

## Per-Environment Overrides

Vici uses separate `.env.*` files for docker-compose services, each scoped to a single container:

| File | Service |
|---|---|
| `.env.app` | FastAPI application |
| `.env.postgres` | PostgreSQL database |
| `.env.opensearch` | OpenSearch (Jaeger storage backend) |
| `.env.temporal` | Temporal server |
| `.env.temporal-ui` | Temporal UI |
| `.env.jaeger-query` | Jaeger query service |
| `.env.grafana` | Grafana dashboard |

For production on GKE, environment variables are managed via GCP Secret Manager and delivered to pods through External Secrets Operator (see `infra/components/secrets.py`).

The `ENV` variable controls the environment name. Set it to `local` for development or `production` for production deployments.
