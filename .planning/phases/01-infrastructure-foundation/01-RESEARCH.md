# Phase 1: Infrastructure Foundation - Research

**Researched:** 2026-03-05
**Domain:** FastAPI + SQLModel + Alembic + Inngest + OTel + Prometheus + Twilio webhook security
**Confidence:** HIGH (verified with official docs and PyPI)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Project Layout:**
- Domain-based `src/` structure per AGENTS.md conventions (not file-type layers)
- Domains: `src/sms/` (webhook), `src/jobs/`, `src/workers/` — each with router.py, schemas.py, models.py, service.py, dependencies.py, constants.py, exceptions.py, utils.py
- Global files: `src/config.py`, `src/database.py`, `src/main.py`, `src/exceptions.py`, `src/models.py`
- Import convention: explicit module names across domains (`from src.sms import service as sms_service`)
- Migrations in top-level `migrations/` (Alembic), tests in top-level `tests/`

**ORM / Database:**
- SQLModel (Pydantic-native, SQLAlchemy under the hood) — not SQLAlchemy directly
- Separate models per domain: `models.py` contains SQLModel `table=True` classes; `schemas.py` contains Pydantic `BaseModel` for API request/response
- Never expose raw internal fields like `raw_sms` in API responses
- Alembic autogenerate from SQLModel metadata — import all domain models in `migrations/env.py` before running autogenerate
- No pgvector extension — Pinecone handles all vector storage; PostgreSQL stays vanilla (use `postgres:16`, NOT `pgvector/pgvector:pg16`)
- Alembic migration file naming: `YYYY-MM-DD_slug.py` format per AGENTS.md

**Observability:**
- Jaeger (`jaegertracing/all-in-one`) added to Docker Compose — UI at `http://localhost:16686`, OTLP gRPC at port 4317
- App connects via `OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317`
- Trace context propagated across async handoff by injecting W3C `traceparent` into Inngest event payload; Inngest function extracts it and starts a child span
- structlog integrated with OTel: custom processor auto-injects `trace_id` and `span_id` from active span into every log line

**Rate Limiting:**
- Threshold: 5 messages per minute per phone number
- PostgreSQL TTL counter: dedicated `rate_limit` table with columns `(phone_hash, created_at, count)` — upsert increments count per 1-minute bucket
- On breach: return HTTP 200 with empty TwiML body
- Webhook security gate order (cheapest to most expensive):
  1. Twilio signature validation (crypto only, no DB) → 403 on failure
  2. MessageSid idempotency check (one DB read) → empty TwiML 200 on duplicate
  3. Rate limit check (upsert on rate_limit table) → empty TwiML 200 on breach
  4. Fire Inngest `message.received` event → return HTTP 200

### Claude's Discretion
- Exact Prometheus metric names and histogram bucket boundaries
- Phone number hashing algorithm (SHA-256 of E.164 normalized number is standard)
- Inngest `process-message` stub body (just a log statement in Phase 1)
- Docker Compose health check configuration details

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SEC-01 | Twilio X-Twilio-Signature HMAC validation; HTTP 403 on failure | `RequestValidator` dependency pattern documented; URL reconstruction for proxies critical |
| SEC-02 | MessageSid deduplication before any processing (unique constraint + idempotency check) | `inbound_message` table with unique MessageSid + `ON CONFLICT DO NOTHING` pattern |
| SEC-03 | Per-phone rate limiting (5/min) using PostgreSQL TTL counter table | `rate_limit(phone_hash, created_at, count)` upsert pattern; no Redis needed |
| SEC-04 | Audit table for raw SMS + raw GPT response (GPT column populated in Phase 2) | Schema columns exist in Phase 1 migration; write happens in Phase 2 |
| IDN-01 | Phone number auto-registration on first inbound message (E.164, no signup) | `phone` table with upsert; Twilio `From` field is already E.164 normalized |
| IDN-02 | `created_at` timestamp on phone identity for number recycling detection | SQLModel column with `default=datetime.utcnow` |
| OBS-02 | Prometheus `/metrics` endpoint with request count, latency histograms, error rates | `prometheus-fastapi-instrumentator` — one-liner setup |
| OBS-03 | OTel traces on all inbound/outbound HTTP and DB queries; OTLP export to Jaeger | `opentelemetry-instrumentation-fastapi` + `opentelemetry-instrumentation-sqlalchemy` + OTLP gRPC exporter |
| OBS-04 | Structured JSON logs with phone hash, message_id, trace_id on every request | `structlog` with custom OTel processor; trace_id extracted from active span |
| ASYNC-01 | Fire `message.received` Inngest event immediately after validation; return 200 before any GPT work | `inngest_client.send()` (async) called before returning TwiML response |
| ASYNC-03 | Inngest Dev Server runs locally via Docker Compose | `inngest/inngest` Docker image; `INNGEST_DEV=1` and `INNGEST_BASE_URL` env vars |
| DEP-01 | `docker compose up` starts PostgreSQL 16 + Inngest Dev Server; Alembic migrations run | Alembic entrypoint script in app container startup command |
| DEP-02 | `/health` endpoint returning service status | FastAPI route with DB connectivity check |
</phase_requirements>

---

## Summary

Phase 1 builds the full infrastructure skeleton that all subsequent phases depend on. The stack is FastAPI + SQLModel + Alembic (PostgreSQL 16, vanilla — no pgvector) + Inngest (async event processing) + Jaeger (OTel traces) + structlog (structured logs) + Prometheus (metrics). This is a greenfield Python project; nothing is being migrated or refactored.

The most critical design constraint is the **webhook security gate order**: Twilio signature validation (pure crypto, no DB) runs first and returns 403 on failure; MessageSid idempotency (one DB read) runs second; rate limiting (PostgreSQL upsert) runs third; only then does the Inngest event fire and HTTP 200 return. This ordering prevents any DB write from occurring on an invalid request and any GPT cost from occurring before deduplication.

The second critical design constraint is **SQLModel's dual-driver requirement**: SQLModel uses SQLAlchemy under the hood, and SQLAlchemy requires both `asyncpg` (for async queries) and `psycopg2-binary` + `greenlet` (for synchronous operations it uses internally, including Alembic). Failing to install all three causes cryptic import errors at startup.

**Primary recommendation:** Build three sub-plans in dependency order — (1) project scaffold + Docker Compose + Alembic setup + async DB session, (2) security gates (Twilio validation + idempotency + rate limiting + phone identity + audit table), (3) observability stack (structlog + OTel + Prometheus) + Inngest client + event emission + health endpoint.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.12 | Runtime | Best balance of performance and ecosystem stability as of 2026 |
| FastAPI | >=0.110.0 | HTTP framework | Required by `inngest` >=0.5.x; async-native, Pydantic v2 integrated |
| SQLModel | latest | ORM (Pydantic-native SQLAlchemy wrapper) | Locked decision; Pydantic models double as DB models |
| asyncpg | >=0.29 | Async PostgreSQL driver | Required for `create_async_engine("postgresql+asyncpg://...")` |
| psycopg2-binary | latest | Sync PostgreSQL driver | Required by SQLModel/SQLAlchemy for internal sync ops (Alembic env.py) |
| greenlet | latest | SQLAlchemy async bridge | Required dependency for SQLAlchemy async support |
| Alembic | >=1.13 | Database migrations | First-class SQLAlchemy/SQLModel integration; async-capable env.py |
| inngest | 0.5.17 (latest) | Async event processing | Python 3.10+ minimum; FastAPI >=0.110.0 required |
| twilio | >=9.0 | Twilio SDK + RequestValidator | Signature validation + TwiML generation |
| structlog | >=24.0 | Structured JSON logging | Custom OTel processor injects trace_id/span_id automatically |
| opentelemetry-api | latest stable | OTel API | Tracer/span creation |
| opentelemetry-sdk | latest stable | OTel SDK | TracerProvider, BatchSpanProcessor |
| opentelemetry-exporter-otlp | latest stable | OTLP gRPC exporter to Jaeger | Exports spans to `jaeger:4317` |
| opentelemetry-instrumentation-fastapi | latest stable | Auto-instrument FastAPI routes | Automatic HTTP spans |
| opentelemetry-instrumentation-sqlalchemy | latest stable | Auto-instrument DB queries | Automatic query spans |
| prometheus-fastapi-instrumentator | latest stable | `/metrics` endpoint | One-liner setup; exposes Prometheus-formatted counters and histograms |
| pydantic-settings | >=2.0 | Typed env var config | `BaseSettings` binds env vars at startup; validates types |
| uvicorn[standard] | >=0.30 | ASGI server | uvloop + httptools for production performance |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| python-dotenv | >=1.0 | .env file loading | Local dev only |
| httpx | >=0.27 | Test HTTP client | pytest test fixtures against FastAPI |
| pytest | >=8.0 | Test runner | All tests |
| pytest-asyncio | >=0.23 | Async test support | Required for async FastAPI routes |
| ruff | latest | Linting + formatting | Replaces flake8+black+isort per AGENTS.md |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `postgres:16` Docker image | `pgvector/pgvector:pg16` | pgvector image needed only if adding vector extension; locked decision uses Pinecone, so vanilla postgres:16 is correct |
| `prometheus-fastapi-instrumentator` | Manual Prometheus counters | Instrumentator gives latency histograms for free in one line; custom counters added on top if needed |
| `inngest/inngest` Docker image | `npx inngest-cli` | Docker image integrates cleanly with Docker Compose; CLI requires Node.js in the compose network |

### Installation

```bash
uv add fastapi "uvicorn[standard]" sqlmodel asyncpg psycopg2-binary greenlet alembic \
       inngest twilio \
       pydantic-settings structlog python-dotenv \
       opentelemetry-api opentelemetry-sdk \
       opentelemetry-exporter-otlp \
       opentelemetry-instrumentation-fastapi \
       opentelemetry-instrumentation-sqlalchemy \
       prometheus-fastapi-instrumentator

uv add --dev pytest pytest-asyncio httpx ruff
```

---

## Architecture Patterns

### Recommended Project Structure

```
src/
├── main.py              # FastAPI app factory, lifespan hooks, OTel init, Inngest serve
├── config.py            # Global pydantic-settings BaseSettings
├── database.py          # SQLModel async engine + session factory
├── exceptions.py        # Global exception handlers
├── models.py            # Re-exports all domain models (for Alembic import)
├── sms/
│   ├── router.py        # POST /webhook/sms
│   ├── schemas.py       # TwilioWebhookForm Pydantic schema
│   ├── models.py        # InboundMessage SQLModel table=True
│   ├── service.py       # SMS processing coordination (Phase 1: just validates + emits)
│   ├── dependencies.py  # validate_twilio_request Depends()
│   ├── constants.py     # RATE_LIMIT_WINDOW_SECONDS, MAX_MESSAGES_PER_WINDOW
│   └── exceptions.py    # TwilioSignatureInvalid, RateLimitExceeded
├── jobs/
│   ├── models.py        # Job SQLModel table=True (schema only, Phase 1)
│   └── schemas.py       # JobCreate, JobRead Pydantic models
└── workers/
    ├── models.py        # Worker SQLModel table=True (schema only, Phase 1)
    └── schemas.py       # WorkerCreate Pydantic models

migrations/
├── env.py               # Async Alembic setup; imports all SQLModel models
├── script.py.mako       # Must include `import sqlmodel`
└── versions/
    └── 2026-03-05_initial_schema.py

tests/
├── conftest.py          # Fixtures: async test DB, mock Twilio validator
└── sms/
    └── test_webhook.py  # SEC-01, SEC-02, SEC-03 integration tests

docker-compose.yml
Dockerfile
pyproject.toml
alembic.ini
```

### Pattern 1: Inngest Client + Endpoint Setup

**What:** Create an `inngest.Inngest` client, define functions with `@inngest_client.create_function`, then serve the Inngest endpoint via `inngest.fast_api.serve(app, client, [fn_list])`. This registers `POST /api/inngest` on the FastAPI app for the Dev Server to invoke.

**When to use:** Always — this is the required integration pattern.

```python
# src/main.py
import inngest
import inngest.fast_api
from fastapi import FastAPI

inngest_client = inngest.Inngest(
    app_id="vici",
    # is_production defaults based on INNGEST_DEV env var
)

@inngest_client.create_function(
    fn_id="process-message",
    trigger=inngest.TriggerEvent(event="message.received"),
)
async def process_message(ctx: inngest.Context) -> str:
    # Phase 1: stub — just log receipt
    ctx.logger.info("message.received event consumed", data=ctx.event.data)
    return "ok"

app = FastAPI()

# Registers POST /api/inngest
inngest.fast_api.serve(app, inngest_client, [process_message])
```

**Environment variables for local dev:**
```bash
INNGEST_DEV=1                        # enables dev mode
INNGEST_BASE_URL=http://inngest:8288 # where SDK finds the Dev Server (Docker network)
```

### Pattern 2: Sending an Inngest Event from the Webhook

**What:** After validation gates pass, fire the event asynchronously and immediately return TwiML. The event carries the validated webhook payload plus the W3C `traceparent` header for trace context propagation.

```python
# src/sms/service.py
from opentelemetry import trace
from opentelemetry.propagate import inject
import inngest

async def emit_message_received_event(
    inngest_client: inngest.Inngest,
    message_sid: str,
    from_number: str,
    body: str,
) -> None:
    # Inject active OTel span context as W3C traceparent into event data
    carrier: dict = {}
    inject(carrier)  # populates {"traceparent": "00-<trace_id>-<span_id>-01"}

    await inngest_client.send(
        inngest.Event(
            name="message.received",
            data={
                "message_sid": message_sid,
                "from_number": from_number,
                "body": body,
                "otel": carrier,  # {"traceparent": "..."}
            },
        )
    )
```

In the Inngest function (Phase 2+), extract the traceparent and create a child span using `opentelemetry.propagate.extract(ctx.event.data["otel"])`.

### Pattern 3: Twilio Signature Validation Dependency

**What:** A FastAPI `Depends()` that validates the `X-Twilio-Signature` header using Twilio's `RequestValidator`. Must reconstruct the public URL — not the internal FastAPI URL — because the HMAC is computed against the URL Twilio called.

**Critical pitfall:** Behind a proxy (Railway, Render, ngrok), `request.url` reflects the internal URL (`http://app:8000/webhook/sms`) but Twilio signed against `https://yourdomain.com/webhook/sms`. HMAC will never match unless the URL is reconstructed from config.

```python
# src/sms/dependencies.py
import hashlib
from fastapi import Depends, HTTPException, Request, status
from twilio.request_validator import RequestValidator
from src.config import settings

async def validate_twilio_request(request: Request) -> dict:
    validator = RequestValidator(settings.twilio_auth_token)
    form_data = dict(await request.form())

    # Reconstruct the URL Twilio actually called
    # Use WEBHOOK_BASE_URL env var set to the public-facing URL
    path = request.url.path
    url = f"{settings.webhook_base_url}{path}"

    signature = request.headers.get("X-Twilio-Signature", "")

    if not validator.validate(url, form_data, signature):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Twilio signature",
        )
    return form_data
```

**Config:**
```python
# src/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    twilio_auth_token: str
    webhook_base_url: str = "http://localhost:8000"  # override in prod
    database_url: str
    inngest_dev: bool = False
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    # ...

settings = Settings()
```

### Pattern 4: SQLModel Async Session Dependency

**What:** `create_async_engine` with asyncpg driver + `async_sessionmaker` with `expire_on_commit=False`. Both sync and async drivers must be installed.

```python
# src/database.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlmodel import SQLModel
from typing import AsyncGenerator
from src.config import settings

engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
```

`expire_on_commit=False` is required: in async mode, accessing attributes after `commit()` would trigger a lazy-load which fails outside a session context.

### Pattern 5: Alembic Async env.py with SQLModel

**What:** Alembic must use `asyncio.run()` + `conn.run_sync()` for async engines. SQLModel's metadata must be the `target_metadata`. All domain models must be imported before autogenerate runs.

```python
# migrations/env.py (key sections)
import asyncio
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlmodel import SQLModel
from alembic import context

# CRITICAL: import all domain models so SQLModel.metadata is populated
from src.sms.models import InboundMessage  # noqa: F401
from src.jobs.models import Job  # noqa: F401
from src.workers.models import Worker  # noqa: F401

target_metadata = SQLModel.metadata

def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

async def run_async_migrations():
    connectable = async_engine_from_config(
        context.config.get_section(context.config.config_ini_section),
        prefix="sqlalchemy.",
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()

asyncio.run(run_async_migrations())
```

**alembic.ini — filename format:**
```ini
file_template = %%(year)d-%%(month).2d-%%(day).2d_%%(slug)s
```

**script.py.mako — must add sqlmodel import:**
```
import sqlmodel
```

### Pattern 6: OTel Setup + structlog Integration

**What:** Initialize TracerProvider with OTLP gRPC exporter in the FastAPI lifespan. Then configure structlog with a custom processor that reads the active OTel span and injects `trace_id` and `span_id` into every log record automatically.

```python
# src/main.py (lifespan)
from contextlib import asynccontextmanager
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
import structlog

def add_otel_context(logger, method_name, event_dict):
    """structlog processor: injects trace_id and span_id from active OTel span."""
    span = trace.get_current_span()
    if span and span.is_recording():
        ctx = span.get_span_context()
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict

def configure_otel(endpoint: str, service_name: str = "vici"):
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

def configure_structlog():
    structlog.configure(
        processors=[
            add_otel_context,           # inject trace_id, span_id
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
    )

@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_otel(settings.otel_exporter_otlp_endpoint)
    configure_structlog()
    FastAPIInstrumentor.instrument_app(app)
    SQLAlchemyInstrumentor().instrument()
    yield

app = FastAPI(lifespan=lifespan)
```

### Pattern 7: Prometheus Metrics

**What:** `prometheus-fastapi-instrumentator` wraps the entire FastAPI app in one call and exposes `/metrics`. Custom business metrics (SMS processed, rate limit breaches) are added as `prometheus_client` counters.

```python
# src/main.py
from prometheus_fastapi_instrumentator import Instrumentator

# After app = FastAPI(...)
Instrumentator().instrument(app).expose(app)
# Default metrics: http_requests_total, http_request_duration_seconds histogram
```

**Custom metrics (discretionary):**
```python
from prometheus_client import Counter, Histogram

sms_received_total = Counter("vici_sms_received_total", "Total inbound SMS")
sms_rate_limited_total = Counter("vici_sms_rate_limited_total", "SMS dropped by rate limit")
sms_duplicate_total = Counter("vici_sms_duplicate_total", "Duplicate MessageSid dropped")
inngest_event_emit_duration = Histogram(
    "vici_inngest_event_emit_seconds",
    "Time to send Inngest event",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0],
)
```

### Pattern 8: Docker Compose

**What:** Three services — `postgres` (vanilla PostgreSQL 16), `inngest` (Dev Server), `app` (FastAPI). App startup command runs Alembic migrations before uvicorn. Inngest service points at the app's `/api/inngest` endpoint within the Docker network.

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: vici
      POSTGRES_USER: vici
      POSTGRES_PASSWORD: vici
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U vici"]
      interval: 5s
      timeout: 5s
      retries: 5
    ports:
      - "5432:5432"

  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "16686:16686"   # Jaeger UI
      - "4317:4317"     # OTLP gRPC

  inngest:
    image: inngest/inngest:latest
    command: "inngest dev -u http://app:8000/api/inngest"
    ports:
      - "8288:8288"     # Inngest Dev Server UI
    depends_on:
      - app

  app:
    build: .
    depends_on:
      postgres:
        condition: service_healthy
      jaeger:
        condition: service_started
    command: >
      sh -c "alembic upgrade head && uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload"
    environment:
      DATABASE_URL: postgresql+asyncpg://vici:vici@postgres:5432/vici
      INNGEST_DEV: "1"
      INNGEST_BASE_URL: http://inngest:8288
      OTEL_EXPORTER_OTLP_ENDPOINT: http://jaeger:4317
      WEBHOOK_BASE_URL: http://localhost:8000
      TWILIO_AUTH_TOKEN: ${TWILIO_AUTH_TOKEN}
      TWILIO_ACCOUNT_SID: ${TWILIO_ACCOUNT_SID}
    ports:
      - "8000:8000"
```

**Note on Inngest image tag:** As of March 2026, the documented example uses `inngest/inngest:v0.27.0` but the image is regularly updated. Use `latest` for local dev or pin a recent tag at build time.

### Anti-Patterns to Avoid

- **Business logic in the router:** The webhook route must only call the service and return TwiML. All gate logic (validation, idempotency, rate limit) lives in dependencies or service layer.
- **Passing request-scoped session to Inngest send:** The Inngest `send()` call happens within the request handler — this is fine. The Inngest function executes separately and creates its own session.
- **Reconstructing URL from `request.url`:** Behind a proxy, this returns the internal URL, breaking HMAC validation. Always use `settings.webhook_base_url` + path.
- **Forgetting `psycopg2-binary` and `greenlet`:** SQLModel uses SQLAlchemy which requires the sync driver for Alembic env.py even in an otherwise-async project. Missing these causes cryptic import errors.
- **Using `inngest.ContextSync` instead of `inngest.Context`:** For `async def` Inngest functions, use `inngest.Context`; `inngest.ContextSync` is for `def` (sync) functions.
- **Skipping `import sqlmodel` in script.py.mako:** Alembic migration files that use SQLModel column types will fail to import without this.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Twilio HMAC validation | Custom HMAC comparison | `twilio.request_validator.RequestValidator` | Edge cases: URL encoding, parameter sorting, timing-safe comparison all handled |
| Prometheus `/metrics` endpoint | Custom metrics endpoint | `prometheus-fastapi-instrumentator` | Provides latency histograms, request counters, response size automatically |
| OTel span creation for HTTP | Manual span wrapping of every route | `FastAPIInstrumentor.instrument_app(app)` | Auto-instruments all routes, propagates W3C trace context on inbound requests |
| SQLAlchemy DB query spans | Manual span wrapping of queries | `SQLAlchemyInstrumentor().instrument()` | Automatically wraps every execute() call |
| TwiML response construction | Hand-built XML strings | `twilio.twiml.messaging_response.MessagingResponse` | Handles XML encoding, nested elements, spec compliance |
| Structured JSON log format | Custom logging formatter | `structlog` with `JSONRenderer()` | Context binding, processor chain, thread-safe |
| Rate limit cleanup | Cron job or scheduled task | Lazy cleanup: delete stale rows on next request from that phone | Simpler ops; stale rows are tiny; cleanup is O(1) per phone |

**Key insight:** The observability stack (OTel + structlog + Prometheus) looks like it would require significant custom code, but the three instrumentator libraries reduce it to roughly 20 lines of setup code. Resist the urge to "understand" the low-level API before reaching for the high-level wrappers.

---

## Common Pitfalls

### Pitfall 1: Twilio Signature URL Mismatch Behind Proxy

**What goes wrong:** `RequestValidator.validate()` returns `False` for every legitimate request in staging/production. The app works in local dev (`webhook_base_url = http://localhost:8000`) but never in deployed environments.

**Why it happens:** `request.url` in FastAPI reflects the internal service URL, not the public URL Twilio used to sign the request. Even `https://` vs `http://` is enough to break the HMAC.

**How to avoid:** Set `WEBHOOK_BASE_URL` as an env var pointing to the public-facing URL (e.g., `https://your-railway-domain.com`). Reconstruct the URL as `f"{settings.webhook_base_url}{request.url.path}"` in the validation dependency.

**Warning signs:** Works locally, fails in staging. Signature check always fails in deployed env.

### Pitfall 2: SQLModel Dual Driver Requirement

**What goes wrong:** `ImportError: greenlet not found` or `ModuleNotFoundError: psycopg2` at startup. Happens even though the app only uses async queries.

**Why it happens:** SQLAlchemy's async mode requires `greenlet` as a dependency. Alembic's `env.py` uses synchronous connection operations internally that require `psycopg2-binary`. Both are needed even in an all-async project.

**How to avoid:** Always install `asyncpg`, `psycopg2-binary`, and `greenlet` together. Verify with `uv run python -c "import asyncpg, psycopg2, greenlet"`.

**Warning signs:** App starts fine but Alembic `upgrade head` fails on first run.

### Pitfall 3: Inngest Dev Server Can't Reach App

**What goes wrong:** The Inngest Dev Server UI shows no functions registered. Inngest events fire but nothing is consumed.

**Why it happens:** The `inngest dev -u http://app:8000/api/inngest` command must use the Docker service name (`app`), not `localhost`. If the app isn't listening on `0.0.0.0`, the Inngest container can't connect.

**How to avoid:** Start uvicorn with `--host 0.0.0.0`. Use the Docker service name in the `inngest dev -u` URL. Wait for the app to be healthy before Inngest starts (add `depends_on: app`).

**Warning signs:** Inngest UI shows "No apps connected." Functions registered but never triggered.

### Pitfall 4: Missing Models Import in Alembic env.py

**What goes wrong:** `alembic revision --autogenerate` generates an empty migration. No tables are created even though SQLModel models are defined.

**Why it happens:** Alembic can only see models that have been imported before `SQLModel.metadata` is read. If domain model files are never imported in `env.py`, the metadata is empty.

**How to avoid:** In `migrations/env.py`, explicitly import every domain model file that contains `SQLModel` classes with `table=True`. Use a `# noqa: F401` comment to suppress "unused import" linting warnings.

**Warning signs:** Migration file is empty. `alembic upgrade head` succeeds but no tables exist in the database.

### Pitfall 5: OTel Not Initialized Before FastAPIInstrumentor

**What goes wrong:** No spans appear in Jaeger. OTel instrumentation silently does nothing.

**Why it happens:** `FastAPIInstrumentor.instrument_app(app)` must be called after `trace.set_tracer_provider(provider)` is called. If called before, it uses the default no-op provider.

**How to avoid:** Initialize TracerProvider in the FastAPI `lifespan` function, before yielding. Call `instrument_app` immediately after `set_tracer_provider`. The lifespan runs before any requests are served.

**Warning signs:** Jaeger UI shows no traces. `trace.get_current_span()` returns a `NonRecordingSpan`.

### Pitfall 6: Rate Limit Table Grows Without Cleanup

**What goes wrong:** The `rate_limit` table accumulates stale rows indefinitely. At scale, the upsert query slows down as it scans old rows.

**Why it happens:** The lazy-cleanup approach (delete stale rows for a phone on next request) requires an explicit `DELETE WHERE created_at < now() - interval '1 minute'` in the same transaction as the upsert. Easy to forget to implement the cleanup half.

**How to avoid:** The upsert transaction for any phone must first delete that phone's old windows, then upsert the current window. One SQL statement handles both: delete stale + insert current.

**Warning signs:** `rate_limit` table row count grows at the same rate as inbound messages. Upsert query time increases over time.

---

## Code Examples

### Verified: Inngest Event Send Pattern

```python
# Source: https://github.com/inngest/inngest-py + https://www.inngest.com/docs/getting-started/python-quick-start
import inngest
from opentelemetry.propagate import inject

async def send_message_received_event(
    inngest_client: inngest.Inngest,
    payload: dict,
) -> None:
    carrier: dict = {}
    inject(carrier)  # Injects {"traceparent": "00-<trace>-<span>-01"}

    await inngest_client.send(
        inngest.Event(
            name="message.received",
            data={**payload, "otel": carrier},
        )
    )
```

### Verified: Prometheus + OTel Lifespan Setup

```python
# Source: https://last9.io/blog/integrating-opentelemetry-with-fastapi/ (verified)
# Source: https://github.com/trallnag/prometheus-fastapi-instrumentator (verified)
from contextlib import asynccontextmanager
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from prometheus_fastapi_instrumentator import Instrumentator
import structlog

@asynccontextmanager
async def lifespan(app):
    # OTel setup
    resource = Resource.create({"service.name": "vici"})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    SQLAlchemyInstrumentor().instrument()
    yield

app = FastAPI(lifespan=lifespan)
Instrumentator().instrument(app).expose(app)  # Adds /metrics
```

### Verified: SQLModel Table Model Pattern

```python
# Source: https://sqlmodel.tiangolo.com/tutorial/fastapi/session-with-dependency/
from sqlmodel import SQLModel, Field
from datetime import datetime
from typing import Optional
import uuid

class InboundMessage(SQLModel, table=True):
    __tablename__ = "inbound_message"

    id: Optional[int] = Field(default=None, primary_key=True)
    message_sid: str = Field(unique=True, index=True)  # Twilio MessageSid (idempotency key)
    phone_hash: str = Field(index=True)                # SHA-256 of E.164 From number
    body: str
    raw_sms: str                                        # Audit trail (SEC-04)
    raw_gpt_response: Optional[str] = None             # Populated in Phase 2
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

### Verified: Rate Limit Upsert Pattern

```python
# PostgreSQL-only rate limiting using TTL counter table
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
import hashlib

async def check_rate_limit(
    session: AsyncSession,
    from_number: str,
    window_seconds: int = 60,
    max_count: int = 5,
) -> bool:
    """Returns True if rate limit exceeded, False if OK."""
    phone_hash = hashlib.sha256(from_number.encode()).hexdigest()
    created_at = datetime.utcnow().replace(second=0, microsecond=0)

    # Delete stale windows for this phone (lazy cleanup)
    await session.execute(
        text(
            "DELETE FROM rate_limit "
            "WHERE phone_hash = :phone_hash AND created_at < :cutoff"
        ),
        {"phone_hash": phone_hash, "cutoff": created_at - timedelta(minutes=1)},
    )

    # Upsert current window
    result = await session.execute(
        text(
            "INSERT INTO rate_limit (phone_hash, created_at, count) "
            "VALUES (:phone_hash, :created_at, 1) "
            "ON CONFLICT (phone_hash, created_at) "
            "DO UPDATE SET count = rate_limit.count + 1 "
            "RETURNING count"
        ),
        {"phone_hash": phone_hash, "created_at": created_at},
    )
    await session.commit()
    count = result.scalar_one()
    return count > max_count
```

### Verified: Webhook Security Gate Order

```python
# src/sms/router.py
from fastapi import APIRouter, Depends, Request, Response
from twilio.twiml.messaging_response import MessagingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import get_session
from src.sms.dependencies import validate_twilio_request
from src.sms.service import sms_service

router = APIRouter()

@router.post("/webhook/sms")
async def webhook_sms(
    request: Request,
    form_data: dict = Depends(validate_twilio_request),  # Gate 1: 403 on bad sig
    session: AsyncSession = Depends(get_session),
):
    message_sid = form_data.get("MessageSid")
    from_number = form_data.get("From")
    body = form_data.get("Body", "")

    # Gate 2: idempotency check
    is_duplicate = await sms_service.check_duplicate(session, message_sid)
    if is_duplicate:
        return Response(content=str(MessagingResponse()), media_type="application/xml")

    # Gate 3: rate limit
    is_limited = await sms_service.check_rate_limit(session, from_number)
    if is_limited:
        return Response(content=str(MessagingResponse()), media_type="application/xml")

    # Gate 4: store + emit Inngest event
    await sms_service.process(session, message_sid, from_number, body)

    return Response(content=str(MessagingResponse()), media_type="application/xml")
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| FastAPI `BackgroundTasks` for async processing | Inngest events for durable async processing | Project decision | Inngest provides retry, observability, and step functions; BackgroundTasks provides none of these |
| pgvector for vector storage | Pinecone (external service) | Project decision | PostgreSQL stays vanilla; no pgvector extension installation friction |
| Redis for rate limiting | PostgreSQL TTL counter table | Project decision | Reduces infrastructure dependencies at v1 scale |
| uvicorn startup hook for OTel init | FastAPI `lifespan` context manager | FastAPI 0.93+ | `@app.on_event("startup")` is deprecated; use `lifespan` |
| SQLAlchemy direct | SQLModel (Pydantic-native wrapper) | Project decision | SQLModel models double as Pydantic schemas; reduces boilerplate |

**Deprecated / outdated:**
- `@app.on_event("startup")` / `@app.on_event("shutdown")`: Deprecated in FastAPI; use `lifespan` context manager
- `inngest.fast_api.serve` module path: As of inngest 0.5.x, it's `inngest.fast_api` (not `inngest.fastapi` — check PyPI for current module name)
- IVFFlat pgvector index: Not applicable (no pgvector); noted here because prior research files reference it

---

## Open Questions

1. **Inngest module name: `inngest.fast_api` vs `inngest.fastapi`**
   - What we know: The GitHub README uses `inngest.fast_api.serve()` and PyPI 0.5.17 confirms FastAPI support
   - What's unclear: Whether the module is `inngest.fast_api` or `inngest.fastapi` (Python naming varies)
   - Recommendation: Verify with `python -c "import inngest.fast_api"` after install before writing code

2. **OTel exporter package name: `opentelemetry-exporter-otlp` vs `opentelemetry-exporter-otlp-proto-grpc`**
   - What we know: The gRPC class is `OTLPSpanExporter` from `opentelemetry.exporter.otlp.proto.grpc.trace_exporter`
   - What's unclear: Whether the meta-package `opentelemetry-exporter-otlp` or the specific `opentelemetry-exporter-otlp-proto-grpc` should be pinned
   - Recommendation: Install `opentelemetry-exporter-otlp` (meta-package) which pulls gRPC and HTTP variants

3. **`prometheus-fastapi-instrumentator` maintenance status**
   - What we know: The primary repo (`trallnag/prometheus-fastapi-instrumentator`) exists on PyPI and GitHub; a fork (`macbre/prometheus-fastapi-instrumentator`) also appeared in search results
   - What's unclear: Whether the primary package is still actively maintained for FastAPI 0.110+
   - Recommendation: `uv add prometheus-fastapi-instrumentator` and check the installed version works with `Instrumentator().instrument(app).expose(app)`; if import fails, the `starlette-exporter` package is an alternative

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`) — Wave 0 creates |
| Quick run command | `pytest tests/ -x -q` |
| Full suite command | `pytest tests/ -v --tb=short` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SEC-01 | POST /webhook/sms with invalid signature → HTTP 403 | integration | `pytest tests/sms/test_webhook.py::test_invalid_signature -x` | ❌ Wave 0 |
| SEC-01 | POST /webhook/sms with valid signature → HTTP 200 | integration | `pytest tests/sms/test_webhook.py::test_valid_signature -x` | ❌ Wave 0 |
| SEC-02 | Same MessageSid twice → only one DB record | integration | `pytest tests/sms/test_webhook.py::test_idempotency -x` | ❌ Wave 0 |
| SEC-03 | >5 messages/min from same phone → HTTP 200 empty TwiML (no crash) | integration | `pytest tests/sms/test_webhook.py::test_rate_limit -x` | ❌ Wave 0 |
| SEC-04 | Audit table row created for each valid inbound message | integration | `pytest tests/sms/test_webhook.py::test_audit_row_created -x` | ❌ Wave 0 |
| IDN-01 | First message from phone → phone row auto-created | integration | `pytest tests/sms/test_webhook.py::test_phone_auto_register -x` | ❌ Wave 0 |
| IDN-02 | phone.created_at is set on first message | unit | `pytest tests/sms/test_webhook.py::test_phone_created_at -x` | ❌ Wave 0 |
| OBS-02 | GET /metrics returns Prometheus-formatted text | integration | `pytest tests/test_health.py::test_metrics_endpoint -x` | ❌ Wave 0 |
| OBS-03 | OTel span exported (mock collector) | integration | manual-only in Phase 1 — verify via Jaeger UI | N/A |
| OBS-04 | Log line contains trace_id field | unit | `pytest tests/test_logging.py::test_trace_id_in_log -x` | ❌ Wave 0 |
| ASYNC-01 | Valid webhook → Inngest event sent before 200 returned | integration | `pytest tests/sms/test_webhook.py::test_inngest_event_emitted -x` | ❌ Wave 0 |
| ASYNC-03 | docker compose up → all services healthy | manual | `docker compose up --wait` + `curl http://localhost:8000/health` | N/A |
| DEP-01 | `docker compose up` starts postgres + inngest + applies migrations | manual | `docker compose up --wait && curl localhost:8000/health` | N/A |
| DEP-02 | GET /health returns 200 with service status | integration | `pytest tests/test_health.py::test_health_endpoint -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest tests/ -x -q`
- **Per wave merge:** `pytest tests/ -v --tb=short`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/conftest.py` — shared fixtures: async test DB, mock Twilio `RequestValidator`, mock Inngest client
- [ ] `tests/sms/test_webhook.py` — covers SEC-01, SEC-02, SEC-03, SEC-04, IDN-01, IDN-02, ASYNC-01
- [ ] `tests/test_health.py` — covers DEP-02, OBS-02
- [ ] `tests/test_logging.py` — covers OBS-04
- [ ] `pyproject.toml` — pytest + pytest-asyncio config (`asyncio_mode = "auto"`, test path)
- [ ] Framework install: `uv add --dev pytest pytest-asyncio httpx` — none detected yet

---

## Sources

### Primary (HIGH confidence)

- [inngest PyPI 0.5.17](https://pypi.org/project/inngest/) — current version, Python 3.10+ requirement, FastAPI >=0.110.0
- [inngest-py GitHub](https://github.com/inngest/inngest-py) — FastAPI serve pattern, async send, Context type
- [Inngest Local Development Docs](https://www.inngest.com/docs/local-development) — Docker Compose configuration with inngest/inngest image
- [Inngest Python Quick Start](https://www.inngest.com/docs/getting-started/python-quick-start) — INNGEST_DEV, INNGEST_BASE_URL env vars
- [OTel FastAPI Instrumentation](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/fastapi/fastapi.html) — `FastAPIInstrumentor.instrument_app(app)`
- [OTel + FastAPI (Last9)](https://last9.io/blog/integrating-opentelemetry-with-fastapi/) — TracerProvider, OTLPSpanExporter, BatchSpanProcessor setup
- [prometheus-fastapi-instrumentator GitHub](https://github.com/trallnag/prometheus-fastapi-instrumentator) — one-liner setup
- [Twilio + FastAPI secure webhook](https://www.twilio.com/en-us/blog/build-secure-twilio-webhook-python-fastapi) — RequestValidator dependency pattern
- [SQLModel async (Feldroy 2025)](https://daniel.feldroy.com/posts/til-2025-08-using-sqlmodel-asynchronously-with-fastapi-and-air-with-postgresql) — dual driver requirement, AsyncSession setup
- [SQLModel session with dependency](https://sqlmodel.tiangolo.com/tutorial/fastapi/session-with-dependency/) — official SQLModel docs

### Secondary (MEDIUM confidence)

- [TestDriven SQLModel + Alembic](https://testdriven.io/blog/fastapi-sqlmodel/) — Alembic env.py async pattern with SQLModel metadata
- [Alembic async setup (DEV)](https://dev.to/matib/alembic-with-async-sqlalchemy-1ga) — asyncio.run() + conn.run_sync() pattern

### Tertiary (LOW confidence)

- Training data (Aug 2025 cutoff) — Twilio SDK 9.x API stability, asyncpg version compatibility

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all versions verified against PyPI as of 2026-03-05
- Architecture: HIGH — patterns verified against official docs (Inngest, OTel, SQLModel, Twilio)
- Pitfalls: HIGH — dual-driver gotcha verified by 2025 tutorial; proxy header pitfall documented by Twilio and community

**Research date:** 2026-03-05
**Valid until:** 2026-06-05 (90 days — stable libraries with slow-moving APIs)
