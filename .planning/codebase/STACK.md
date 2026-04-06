# Technology Stack

**Analysis Date:** 2026-04-06

## Languages

**Primary:**
- Python 3.12+ - Application code (`src/`), infrastructure-as-code (`infra/`)

**Secondary:**
- YAML - Docker Compose, CI/CD workflows, Jaeger/Prometheus config
- Pulumi Python - Infrastructure definitions (`infra/components/`)

## Runtime

**Environment:**
- Python 3.12 (specified in `pyproject.toml` `requires-python = ">=3.12"`, Docker base `python:3.12-slim`)

**Package Manager:**
- uv (Astral) - lockfile-based dependency management
- Lockfile: `uv.lock` (present, frozen installs used in CI and Docker)
- No pip/poetry usage; all commands use `uv run` or `uv sync`

## Frameworks

**Core:**
- FastAPI (>=0.135.1) - HTTP framework, async-first, lifespan-based DI
- SQLModel (>=0.0.37) - ORM layer (SQLAlchemy 2.x + Pydantic hybrid)
- SQLAlchemy async (`create_async_engine`, `AsyncSession`) - Database access via `src/database.py`
- Pydantic Settings (>=2.13.1) - Configuration management via `src/config.py`

**Workflow Orchestration:**
- Temporal SDK (>=1.24.0, server 1.26.2) - Durable workflow execution
  - Workflows: `src/temporal/workflows.py`
  - Activities: `src/temporal/activities.py`
  - Worker: `src/temporal/worker.py`

**Testing:**
- pytest (>=9.0.2) with `asyncio_mode = "auto"` in `pyproject.toml`
- pytest-asyncio (>=1.3.0) - Async test support
- pytest-cov (>=7.0.0) - Coverage reporting
- httpx (>=0.28.1) - Async HTTP test client
- aiosqlite (>=0.22.1) - SQLite backend for test isolation (no Postgres in CI)

**Build/Dev:**
- Ruff (>=0.15.5) - Linting and formatting (`target-version = "py312"`, rules: E, F, I)
- Docker - Multi-stage build (`Dockerfile`)
- Docker Compose - Local dev stack (`docker-compose.yml`)

**Infrastructure:**
- Pulumi (>=3.229.0) with `pulumi-gcp` (>=9.18.0) and `pulumi-kubernetes` (>=4.28.0)

## Key Dependencies

**Critical (validated at startup via `src/config.py` `_validate_required_credentials`):**
- `openai` (>=1.0.0) - GPT-5.3 for SMS classification/extraction (`src/extraction/service.py`), embeddings via `text-embedding-3-small` (`src/extraction/utils.py`)
- `pinecone[asyncio]` (>=8.1.0) - Vector DB for job embeddings (`src/extraction/utils.py`)
- `twilio` (>=9.10.2) - SMS sending/receiving, webhook signature validation (`src/sms/`)
- `temporalio` (>=1.24.0) - Durable workflows: message processing, Pinecone sync cron (`src/temporal/`)
- `asyncpg` (>=0.31.0) - PostgreSQL async driver

**Observability:**
- `opentelemetry-api` / `opentelemetry-sdk` / `opentelemetry-exporter-otlp` (>=1.40.0) - Distributed tracing via OTLP/gRPC
- `opentelemetry-instrumentation-fastapi` (>=0.61b0) - Auto-instrument HTTP spans
- `opentelemetry-instrumentation-sqlalchemy` (>=0.61b0) - Auto-instrument DB spans
- `prometheus-fastapi-instrumentator` (>=7.1.0) - Prometheus `/metrics` endpoint
- `prometheus_client` - Custom metrics: GPT calls, tokens, queue depth (`src/metrics.py`)
- `braintrust` (>=0.0.100) - LLM observability, wraps OpenAI client (`src/main.py` lifespan)
- `structlog` (>=25.5.0) - Structured JSON logging with OTel trace context injection

**Resilience:**
- `tenacity` (>=8.0.0) - Retry with exponential backoff for GPT calls (`src/extraction/service.py`)

**Other:**
- `psycopg2-binary` (>=2.9.11) - Sync PostgreSQL driver (Alembic migrations)
- `python-dotenv` (>=1.2.2) - Env file loading
- `python-multipart` (>=0.0.22) - Form data parsing (Twilio webhooks)
- `greenlet` (>=3.3.2) - Required by SQLAlchemy async
- `alembic` (>=1.18.4) - Database schema migrations (`migrations/`)

## Configuration

**Environment:**
- All config via environment variables through `pydantic_settings.BaseSettings` in `src/config.py`
- Single `Settings` class with nested sub-models: `SmsSettings`, `ExtractionSettings`, `PineconeSettings`, `ObservabilitySettings`, `TemporalSettings`
- Flat env vars remapped into nested models via `@model_validator(mode="after")`
- Settings singleton via `@lru_cache(maxsize=1)` on `get_settings()`
- Per-service env files for Docker Compose: `.env.app`, `.env.postgres`, `.env.temporal`, `.env.grafana`, `.env.jaeger-query`, `.env.opensearch` (contents are secrets; `.env.*.example` files present for docs)

**Required env vars (fail-fast validation at startup):**
- `DATABASE_URL` - PostgreSQL connection string (`postgresql+asyncpg://`)
- `TWILIO_AUTH_TOKEN`, `TWILIO_ACCOUNT_SID`, `TWILIO_FROM_NUMBER`
- `OPENAI_API_KEY`
- `PINECONE_API_KEY`, `PINECONE_INDEX_HOST`
- `TEMPORAL_ADDRESS`
- `WEBHOOK_BASE_URL`
- `ENV` - Environment name

**Build:**
- `pyproject.toml` - Project metadata, deps, tool config (ruff, pytest)
- `alembic.ini` - Migration config (file template: `YYYY-MM-DD_slug`)
- `Dockerfile` - Multi-stage build (builder + runtime), non-root user, healthcheck on `/health`

## Database

**Primary:**
- PostgreSQL 16 (Docker Compose image)
- Async driver: `asyncpg`
- ORM: SQLModel (SQLAlchemy 2.x)
- Naming conventions enforced in `src/database.py` (`POSTGRES_INDEXES_NAMING_CONVENTION`)
- Schema in 3NF: `User`, `Message`, `Job`, `WorkGoal`, `Match`, `RateLimit`, `AuditLog`, `PineconeSyncQueue` (see `src/models.py`)
- Migrations: Alembic with date-prefixed filenames in `migrations/versions/`

**CI/Test:**
- SQLite via `aiosqlite` (`DATABASE_URL: sqlite+aiosqlite:///./test.db` in `ci.yml`)

## Platform Requirements

**Development:**
- Python 3.12+
- uv package manager
- Docker and Docker Compose for local services
- Local Docker Compose services (9 total): postgres, opensearch, jaeger-collector, jaeger-query, app, temporal, temporal-ui, prometheus, grafana
- Ports: 8000 (app), 5432 (Postgres), 7233 (Temporal), 8080 (Temporal UI), 4317/4318 (Jaeger OTLP), 16686 (Jaeger UI), 9090 (Prometheus), 3000 (Grafana), 9200 (OpenSearch)

**Production:**
- Google Cloud Platform (GKE)
- GKE cluster via Pulumi (`infra/components/cluster.py`)
- Google Artifact Registry for Docker images (`infra/components/registry.py`)
- Cloud SQL for PostgreSQL - separate instances for app and Temporal (`infra/components/database.py`)
- External Secrets Operator (ESO) for secret management (`infra/components/secrets.py`)
- cert-manager for TLS certificates (`infra/components/certmanager.py`)
- Workload Identity Federation for CI/CD auth (`infra/components/cd.py`)
- kube-prometheus-stack for monitoring (`infra/components/prometheus.py`)
- Jaeger collector + query on GKE with OpenSearch backend (`infra/components/jaeger.py`, `infra/components/opensearch.py`)
- Environments: dev, staging, prod (`infra/Pulumi.dev.yaml`, `Pulumi.staging.yaml`, `Pulumi.prod.yaml`)
- Hostnames: `dev.usevici.com`, `staging.usevici.com`, `usevici.com`

**CI/CD:**
- GitHub Actions
  - `.github/workflows/ci.yml` - Lint (ruff) + test (pytest) on push/PR to main
  - `.github/workflows/cd-base.yml` - Reusable workflow: build Docker image, push to Artifact Registry, Pulumi deploy
  - `.github/workflows/cd-dev.yml`, `cd-staging.yml`, `cd-prod.yml` - Environment-specific deploy triggers
  - Auth: Workload Identity Federation (no static service account keys)

---

*Stack analysis: 2026-04-06*
