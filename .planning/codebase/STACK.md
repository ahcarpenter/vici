# Tech Stack

> Last updated: 2026-04-03 | Confidence: HIGH | Source: pyproject.toml, docker-compose.yml, codebase inspection

## Runtime

| Component | Technology | Notes |
|-----------|-----------|-------|
| Language | Python 3.12 | |
| Framework | FastAPI | Async, lifespan DI |
| ORM | SQLModel + SQLAlchemy (async) | asyncpg driver for Postgres, aiosqlite for tests |
| Migrations | Alembic | Async env.py with asyncio.run() |
| Package Manager | uv | |

## Data Stores

| Store | Technology | Purpose |
|-------|-----------|---------|
| Primary DB | PostgreSQL 16 | 3NF schema: User, Message, Job, WorkRequest, RateLimit, AuditLog, PineconeSyncQueue |
| Vector Store | Pinecone | Job embeddings via text-embedding-3-small |
| Test DB | SQLite + aiosqlite | No Postgres dependency in tests |

## AI / LLM

| Component | Technology | Notes |
|-----------|-----------|-------|
| Classification + Extraction | OpenAI GPT (gpt-5.3-chat-latest) | beta.chat.completions.parse with discriminated union |
| Embeddings | text-embedding-3-small | Via Pinecone client |
| LLM Observability | Braintrust | wrap_openai wrapper for tracing + evals |

## Orchestration

| Component | Technology | Notes |
|-----------|-----------|-------|
| Workflow Engine | Temporal | temporalio SDK |
| Workflows | ProcessMessageWorkflow | 4 attempts, exponential backoff, on_failure handler |
| | SyncPineconeQueueWorkflow | Cron every 5 min, RPCError for idempotent scheduling |
| Tracing | TracingInterceptor | OTel integration on Client.connect(); worker inherits |

## Messaging

| Component | Technology | Notes |
|-----------|-----------|-------|
| SMS | Twilio | Inbound webhook + outbound REST client |
| Webhook Security | 5-gate chain | Signature validation, rate limiting, user lookup |

## Observability

| Component | Technology | Notes |
|-----------|-----------|-------|
| Structured Logging | structlog | JSON format with OTel trace/span IDs |
| Distributed Tracing | OpenTelemetry -> Jaeger v2 | OpenSearch backend, OTLP/gRPC export |
| Metrics | Prometheus + Grafana | prometheus-fastapi-instrumentator + custom counters |
| Temporal Tracing | TracingInterceptor | Propagates OTel context through workflows/activities |

## Infrastructure

| Component | Technology | Notes |
|-----------|-----------|-------|
| Local Dev | Docker Compose | 9 services: postgres, opensearch, jaeger-collector, jaeger-query, app, temporal, temporal-ui, prometheus, grafana |
| Production | Render.com | render.yaml Blueprint (web service + managed PostgreSQL) |
| CI | GitHub Actions | SQLite tests, ruff linting |
| Container | Multi-stage Dockerfile | Non-root user, HEALTHCHECK on /health |

## Key Libraries

| Library | Version | Purpose |
|---------|---------|---------|
| fastapi | * | Web framework |
| sqlmodel | * | ORM |
| temporalio | * | Workflow orchestration |
| openai | * | GPT API client |
| pinecone | * | Vector store client |
| twilio | * | SMS client |
| braintrust | * | LLM observability |
| structlog | * | Structured logging |
| opentelemetry-* | * | Distributed tracing |
| prometheus-fastapi-instrumentator | * | Metrics |
| ruff | * | Linting + formatting |
