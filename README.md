# Vici

An SMS-driven platform for the gig economy

## How It Works

Workers text in an earnings goal (e.g. "I need $1200 by Thursday of next week."). Job posters text in a job listing with the relevant details (desc, pay, duration, expected done date). GPT classifies each inbound message and extracts structured data from both. Matching algorithm surfaces the gig(s) on-demand that the worker can then do to achieve their earnings goal in the shortest amount of time possible.

## Roadmap

See [here](https://github.com/ahcarpenter/vici/blob/main/.planning/ROADMAP.md) for the current roadmap, and progress.

## Prerequisites

- Docker and Docker Compose
- Python 3.12+ and [uv](https://docs.astral.sh/uv/) (`pip install uv`)
- Accounts with API keys for: Twilio, OpenAI, Pinecone, Braintrust

## Local Setup

1. Clone the repository

   ```bash
   git clone <repo-url>
   cd vici
   ```

2. Copy the example env files for each service and fill in your secrets (see [Environment Variables](#environment-variables) below)

   ```bash
   cp .env.app.example .env.app
   cp .env.postgres.example .env.postgres
   cp .env.opensearch.example .env.opensearch
   cp .env.jaeger-query.example .env.jaeger-query
   cp .env.temporal.example .env.temporal
   cp .env.temporal-ui.example .env.temporal-ui
   cp .env.grafana.example .env.grafana
   ```

3. Start the full stack (Postgres, OpenSearch, Jaeger, Temporal, Prometheus, Grafana, and the API)

   ```bash
   docker compose up
   ```

   The API is available at http://localhost:8000. The Temporal UI is at http://localhost:8080.

4. Apply database migrations (first time and after schema changes)

   ```bash
   uv run alembic upgrade head
   ```

   > **Note:** Migrations run automatically on container startup via the Dockerfile CMD, so this step is only needed when running the API outside Docker.

## Environment Variables

Each service has its own env file. The `.example` files document all required variables -- copy them (step 2 above) and fill in values marked `your_*`.

### `.env.app` -- API service

| Variable | Required | Description | Where to get it |
|---|---|---|---|
| `DATABASE_URL` | Yes | Async PostgreSQL connection string | Pre-filled for local Docker Compose |
| `TWILIO_AUTH_TOKEN` | Yes | Validates inbound webhook signatures | Twilio Console |
| `TWILIO_ACCOUNT_SID` | Yes | Identifies your Twilio account | Twilio Console |
| `TWILIO_FROM_NUMBER` | Yes | Twilio phone number for outbound SMS | Twilio Console |
| `WEBHOOK_BASE_URL` | Yes | Public base URL for this service | `http://localhost:8000` locally; your production domain in GKE |
| `ENV` | Yes | Runtime environment | `development` locally, `production` in GKE |
| `TEMPORAL_ADDRESS` | Yes | Temporal server address | `temporal:7233` (matches Docker Compose) |
| `TEMPORAL_TASK_QUEUE` | No | Temporal task queue name (default: `vici-queue`) | Pre-filled |
| `CRON_SCHEDULE_PINECONE_SYNC` | No | Pinecone sync cron expression (default: `*/5 * * * *`) | Pre-filled |
| `OPENAI_API_KEY` | Yes | GPT classification and embedding calls | platform.openai.com |
| `PINECONE_API_KEY` | Yes | Vector upsert and query | Pinecone Console |
| `PINECONE_INDEX_HOST` | Yes | Your Pinecone index endpoint | Pinecone Console |
| `BRAINTRUST_API_KEY` | Yes | LLM observability and evals | braintrust.dev |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Yes | OpenTelemetry collector endpoint | `http://jaeger-collector:4317` (matches Docker Compose) |
| `OTEL_SERVICE_NAME` | Yes | Service name in traces | `vici` |
| `SMS_RATE_LIMIT_WINDOW_SECONDS` | No | Rate limit sliding window in seconds (default: `60`) | Pre-filled |
| `SMS_RATE_LIMIT_MAX` | No | Max SMS messages per window (default: `5`) | Pre-filled |
| `GIT_SHA` | No | Current git SHA for trace metadata | `dev` locally; set by CI in production |

### `.env.postgres` -- Postgres service

| Variable | Required | Description |
|---|---|---|
| `POSTGRES_DB` | Yes | Database name |
| `POSTGRES_USER` | Yes | Postgres username |
| `POSTGRES_PASSWORD` | Yes | Postgres password -- change `change_me` in production |

### `.env.temporal` -- Temporal service

| Variable | Required | Description |
|---|---|---|
| `DB` | Yes | Temporal persistence backend (`postgres12`) |
| `DB_PORT` | Yes | Postgres port |
| `POSTGRES_USER` | Yes | Postgres username |
| `POSTGRES_PWD` | Yes | Postgres password |
| `POSTGRES_SEEDS` | Yes | Postgres host (e.g. `postgres`) |

### `.env.temporal-ui` -- Temporal UI service

| Variable | Required | Description |
|---|---|---|
| `TEMPORAL_ADDRESS` | Yes | Temporal server address (`temporal:7233`) |

### `.env.opensearch` -- OpenSearch service

| Variable | Required | Description |
|---|---|---|
| `discovery.type` | Yes | Set to `single-node` for local use |
| `DISABLE_SECURITY_PLUGIN` | Yes | Set to `true` for local use |
| `OPENSEARCH_JAVA_OPTS` | No | JVM heap settings (default: `-Xms512m -Xmx512m`) |

### `.env.jaeger-query` -- Jaeger Query service

| Variable | Required | Description |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Yes | OTLP endpoint for self-reporting traces (`http://jaeger-collector:4317`) |

### `.env.grafana` -- Grafana service

| Variable | Required | Description |
|---|---|---|
| `GF_SECURITY_ADMIN_USER` | Yes | Grafana admin username |
| `GF_SECURITY_ADMIN_PASSWORD` | Yes | Grafana admin password |
| `GF_AUTH_ANONYMOUS_ENABLED` | No | Allow anonymous read-only access (`true`) |
| `GF_AUTH_ANONYMOUS_ORG_ROLE` | No | Role for anonymous users (`Viewer`) |

## Running Tests

```bash
uv run pytest
```

Tests use SQLite + aiosqlite -- no Postgres dependency. Temporal activities are mocked in tests. To run with coverage:

```bash
uv run pytest --cov=src --cov-report=term-missing
```

## Linting

```bash
uv run ruff check .
uv run ruff format .
```

## Observability (Local)

After `docker compose up`:

- **Traces**: Jaeger UI at http://localhost:16686
- **Metrics**: Grafana at http://localhost:3000 (admin / admin) -- pre-provisioned FastAPI dashboard
- **Prometheus**: http://localhost:9090

## Documentation

Detailed documentation lives in `docs/`:

- [Getting Started](docs/GETTING-STARTED.md) -- Prerequisites, installation, and first run
- [Architecture](docs/ARCHITECTURE.md) -- System design, component diagram, and data flow
- [Configuration](docs/CONFIGURATION.md) -- Full environment variable reference
- [Development](docs/DEVELOPMENT.md) -- Build commands, code style, and branch conventions
- [Testing](docs/TESTING.md) -- Test framework, running tests, and writing new tests
- [Deployment](docs/DEPLOYMENT.md) -- GKE deployment, CI/CD pipelines, and monitoring
