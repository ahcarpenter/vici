# Vici

Vici is an SMS-driven job matching platform — workers text an earnings goal and receive a ranked list of jobs that let them hit that goal in the shortest possible time.

## How It Works

Workers text in an earnings goal (e.g. "I need $500 this week"). Job posters text in a job listing with a pay rate and duration. GPT classifies each inbound message and extracts structured data from both. The system then matches workers to jobs using earnings math and replies to both parties via Twilio SMS.

## Tech Stack

- Python 3.12, FastAPI
- SQLModel + Alembic (PostgreSQL 16)
- OpenAI GPT via [Braintrust](https://braintrust.dev) (LLM observability + evals)
- Pinecone (vector store for job/worker embeddings)
- Inngest (background jobs, retries, cron sweeps)
- Twilio (inbound + outbound SMS)
- OpenTelemetry -> Jaeger v2 (OpenSearch backend)
- Prometheus + Grafana
- Docker Compose (local dev, 8 services)
- Render.com (production)

## Prerequisites

- Docker and Docker Compose
- Python 3.12+ and [uv](https://docs.astral.sh/uv/) (`pip install uv`)
- Accounts with API keys for: Twilio, OpenAI, Pinecone, Braintrust
- (Optional) Inngest Cloud account — only needed for production; local dev uses the bundled Inngest Dev Server

## Local Setup

1. Clone the repository

   ```bash
   git clone <repo-url>
   cd vici
   ```

2. Copy the example env file and fill in your secrets (see [Environment Variables](#environment-variables) below)

   ```bash
   cp .env.example .env
   ```

3. Start the full stack (Postgres, OpenSearch, Jaeger, Prometheus, Grafana, Inngest Dev Server, and the API)

   ```bash
   docker compose up
   ```

   The API is available at http://localhost:8000. The Inngest Dev Server UI is at http://localhost:8288.

4. Apply database migrations (first time and after schema changes)

   ```bash
   uv run alembic upgrade head
   ```

   > **Note:** Migrations run automatically on container startup via the Dockerfile CMD, so this step is only needed when running the API outside Docker.

## Environment Variables

All required variables are documented in `.env.example`. Copy it to `.env` and fill in the values marked `your_*`.

| Variable | Required | Description | Where to get it |
|---|---|---|---|
| `DATABASE_URL` | Yes | Async PostgreSQL connection string | Pre-filled for local Docker Compose |
| `POSTGRES_DB` | Yes | Postgres database name used by Docker Compose | Pre-filled; change in production |
| `POSTGRES_USER` | Yes | Postgres username used by Docker Compose | Pre-filled; change in production |
| `POSTGRES_PASSWORD` | Yes | Postgres password used by Docker Compose | Pre-filled; change `change_me` in production |
| `TWILIO_AUTH_TOKEN` | Yes | Validates inbound webhook signatures | Twilio Console -> Account -> Auth Token |
| `TWILIO_ACCOUNT_SID` | Yes | Identifies your Twilio account | Twilio Console -> Account -> Account SID |
| `TWILIO_FROM_NUMBER` | Yes | Twilio phone number for outbound SMS | Twilio Console -> Phone Numbers |
| `WEBHOOK_BASE_URL` | Yes | Public base URL for this service | `http://localhost:8000` locally; your Render URL in production |
| `ENV` | Yes | Runtime environment | `development` locally, `production` on Render |
| `INNGEST_DEV` | Yes | `1` enables Inngest Dev Server mode (no signing key needed) | Set to `1` locally, `0` in production |
| `INNGEST_BASE_URL` | Yes | Inngest server URL | `http://localhost:8288` locally, `https://inn.gs` in production |
| `INNGEST_APP_URL` | Yes | URL Docker uses to register the app with Inngest Dev Server | `http://app:8000` (matches docker-compose service name) |
| `INNGEST_SIGNING_KEY` | Prod only | Verifies Inngest webhook signatures in production | Inngest Cloud dashboard -> your app -> Signing Key |
| `INNGEST_EVENT_KEY` | Prod only | Authenticates event sends in production | Inngest Cloud -> Manage -> Event Keys -> Create Key |
| `OPENAI_API_KEY` | Yes | GPT classification and embedding calls | platform.openai.com -> API Keys |
| `PINECONE_API_KEY` | Yes | Vector upsert and query | Pinecone Console -> API Keys |
| `PINECONE_INDEX_HOST` | Yes | Your Pinecone index endpoint | Pinecone Console -> your index -> Host |
| `BRAINTRUST_API_KEY` | Yes | LLM observability and evals via Braintrust | braintrust.dev -> Settings -> API Keys |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Yes | OpenTelemetry collector endpoint | `http://localhost:4317` locally (Jaeger collector) |
| `OTEL_SERVICE_NAME` | Yes | Service name in traces | `vici` |
| `GIT_SHA` | No | Current git SHA for trace metadata | Set to `dev` locally; set by CI/deploy in production |

## Running Tests

```bash
uv run pytest
```

Tests use SQLite + aiosqlite — no Postgres dependency. Inngest HTTP calls are automatically mocked. To run with coverage:

```bash
uv run pytest --cov=src --cov-report=term-missing
```

## Linting

```bash
uv run ruff check .
uv run ruff format .
```

## Project Structure

```
src/
├── main.py              # FastAPI app and lifespan DI graph
├── config.py            # Nested Pydantic Settings (db, twilio, openai, observability)
├── database.py          # Async SQLAlchemy engine and sessionmaker
├── models.py            # Central SQLModel aggregator
├── inngest_client.py    # Inngest function definitions (process-message, sync-pinecone-queue)
├── metrics.py           # Prometheus metric singletons
├── exceptions.py        # Custom exceptions
├── sms/                 # Twilio webhook route, MessageRepository, AuditLogRepository
├── extraction/          # ExtractionService (GPT), PipelineOrchestrator, Pinecone client
├── jobs/                # JobRepository, Job model
├── work_requests/       # WorkRequestRepository, WorkRequest model
├── users/               # User model
└── matches/             # Match model (Phase 3 - not yet implemented)
docker-compose.yml       # Full local stack (8 services)
Dockerfile               # Multi-stage production image
render.yaml              # Render.com Blueprint IaC
pyproject.toml           # Python dependencies managed by uv
alembic/                 # Database migrations
.github/workflows/       # GitHub Actions CI
```

## Observability (Local)

After `docker compose up`:

- **Traces**: Jaeger UI at http://localhost:16686
- **Metrics**: Grafana at http://localhost:3000 (admin / admin) — pre-provisioned FastAPI dashboard
- **Prometheus**: http://localhost:9090

## Deployment

The project deploys to Render.com via the `render.yaml` Blueprint:

1. Push to `main` triggers a Render deploy (web service + managed PostgreSQL)
2. Set all production env vars in the Render dashboard (see [Environment Variables](#environment-variables) table above)
3. Set `INNGEST_DEV=0` and configure `INNGEST_SIGNING_KEY` / `INNGEST_EVENT_KEY` from Inngest Cloud
4. Render runs migrations automatically on startup via the Dockerfile CMD