# Architecture Research

**Domain:** SMS webhook + AI extraction + job matching API
**Researched:** 2026-03-05
**Confidence:** HIGH (stable, mature stack — FastAPI, Twilio, SQLAlchemy, Alembic, pgvector all well-documented)

## Standard Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                         EXTERNAL                                  │
│   ┌──────────────┐                    ┌──────────────────────┐   │
│   │ Twilio SMS   │ POST /webhook/sms  │  OpenAI GPT API      │   │
│   │ (inbound)    │ ─────────────────► │  (classify+extract)  │   │
│   └──────────────┘                    └──────────────────────┘   │
└──────────────────────────────┬───────────────────────────────────┘
                               │ webhook payload
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                         API LAYER (FastAPI)                       │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  POST /webhook/sms   (single inbound route)              │    │
│  │  - Validates Twilio signature                            │    │
│  │  - Parses form-encoded payload                           │    │
│  │  - Returns TwiML (sync, <200ms required by Twilio)       │    │
│  └──────────────────────────┬─────────────────────────────┘     │
└──────────────────────────────┼───────────────────────────────────┘
                               │ normalized message
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                       SERVICE LAYER                               │
│  ┌──────────────────┐  ┌───────────────────┐  ┌──────────────┐  │
│  │ MessageService   │  │  ExtractionService │  │MatchService  │  │
│  │ - classify       │  │  - call GPT        │  │- earnings    │  │
│  │ - route          │  │  - parse response  │  │  math        │  │
│  │ - orchestrate    │  │  - validate schema │  │- rank jobs   │  │
│  └────────┬─────────┘  └─────────┬─────────┘  └──────┬───────┘  │
└───────────┼──────────────────────┼────────────────────┼──────────┘
            │                      │                    │
            ▼                      ▼                    ▼
┌──────────────────────────────────────────────────────────────────┐
│                     REPOSITORY LAYER                              │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐   │
│  │  PhoneRepository │  │  JobRepository   │  │WorkerRepo    │   │
│  │  - get_or_create │  │  - create        │  │- create      │   │
│  │  - lookup        │  │  - find_matching │  │- lookup      │   │
│  └────────┬─────────┘  └────────┬─────────┘  └──────┬───────┘   │
└───────────┼──────────────────────┼────────────────────┼──────────┘
            │                      │                    │
            ▼                      ▼                    ▼
┌──────────────────────────────────────────────────────────────────┐
│                       DATA LAYER                                  │
│  ┌────────────────────────────────────────────────────────┐      │
│  │  PostgreSQL + pgvector                                  │      │
│  │  Tables: phone_numbers, jobs, workers                   │      │
│  │  Extension: vector (pgvector) on jobs.embedding         │      │
│  └────────────────────────────────────────────────────────┘      │
└──────────────────────────────────────────────────────────────────┘
            │
            ▼ Twilio REST API (outbound reply)
┌──────────────────┐
│  SMS reply sent  │
│  to originating  │
│  phone number    │
└──────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| Webhook route | Validate Twilio signature, parse form body, return TwiML | FastAPI router + `twilio.request_validator` |
| MessageService | Classify message type, orchestrate the full flow, format SMS reply | Plain Python class, no I/O |
| ExtractionService | Call OpenAI GPT, parse structured JSON response, validate schema | Async HTTP client (httpx) + Pydantic models |
| MatchService | Execute earnings math query, rank results by date/duration | Pure business logic, no I/O |
| JobRepository | CRUD for job records + matching query | SQLAlchemy async session |
| WorkerRepository | CRUD for worker records | SQLAlchemy async session |
| PhoneRepository | get-or-create phone number identity records | SQLAlchemy async session |
| Alembic migrations | Schema versioning for PostgreSQL | Alembic env.py + migration scripts |
| Settings | Typed environment config | Pydantic `BaseSettings` |
| Observability | Structured logging + request tracing | `structlog` or `python-json-logger` |

## Recommended Project Structure

```
app/
├── main.py                  # FastAPI app factory, lifespan hooks
├── config.py                # Pydantic BaseSettings (env vars)
├── database.py              # SQLAlchemy async engine + session factory
│
├── api/
│   └── v1/
│       ├── __init__.py
│       └── routes/
│           └── webhook.py   # POST /webhook/sms
│
├── services/
│   ├── message_service.py   # Orchestration: classify → extract → match → reply
│   ├── extraction_service.py # OpenAI GPT calls
│   └── match_service.py     # Earnings math + job ranking
│
├── repositories/
│   ├── job_repository.py
│   ├── worker_repository.py
│   └── phone_repository.py
│
├── models/
│   ├── job.py               # SQLAlchemy ORM model
│   ├── worker.py
│   └── phone_number.py
│
├── schemas/
│   ├── job.py               # Pydantic I/O schemas (not ORM)
│   ├── worker.py
│   └── extraction.py        # GPT response shapes
│
└── core/
    ├── twilio.py            # Signature validation dependency
    ├── openai_client.py     # OpenAI async client singleton
    └── logging.py           # Structured log config

alembic/
├── env.py
├── script.py.mako
└── versions/               # Migration files

tests/
├── conftest.py             # Fixtures: test DB, mock Twilio, mock OpenAI
├── api/
│   └── test_webhook.py
├── services/
│   └── test_match_service.py
└── repositories/

docker/
├── Dockerfile
└── docker-compose.yml      # app + postgres (with pgvector image)
```

### Structure Rationale

- **api/v1/routes/:** Versioned routes isolate HTTP concerns. Routes do nothing except call services and return responses. No business logic here.
- **services/:** One service per domain concern. Services coordinate across repositories and external APIs. They are the only layer that "knows" the flow.
- **repositories/:** One repository per ORM model. All SQL is here. Services never write raw queries.
- **models/ vs schemas/:** SQLAlchemy ORM models (models/) stay separate from Pydantic validation schemas (schemas/). This prevents ORM internals leaking into API contracts.
- **core/:** Cross-cutting infrastructure (clients, validators, logging config) that doesn't belong in any domain layer.

## Architectural Patterns

### Pattern 1: Synchronous TwiML Response with Background Task

**What:** The webhook route returns a TwiML `<Response>` immediately (within Twilio's ~15-second timeout), then performs expensive work (GPT call, DB writes) via FastAPI `BackgroundTasks` and sends the SMS reply via the Twilio REST API separately.

**When to use:** When the full processing pipeline (GPT + DB) risks exceeding the Twilio webhook response window. Twilio requires an HTTP 200 response within ~15 seconds or it retries.

**Trade-offs:**
- Pro: Eliminates webhook timeout risk
- Pro: User gets acknowledgment ("Processing your request...") instantly
- Con: Two SMS messages per interaction (acknowledgment + result)
- Con: Adds complexity — background task failures are harder to surface

**Example:**
```python
# routes/webhook.py
from fastapi import BackgroundTasks
from twilio.twiml.messaging_response import MessagingResponse

@router.post("/webhook/sms")
async def sms_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    # Validate Twilio signature (dependency)
    body = await request.form()
    from_number = body["From"]
    message_text = body["Body"]

    # Queue the heavy work — GPT + DB + outbound SMS
    background_tasks.add_task(
        message_service.process, from_number, message_text, session
    )

    # Return empty TwiML immediately — Twilio sees 200 OK
    return Response(content=str(MessagingResponse()), media_type="application/xml")
```

### Pattern 2: Dependency Injection for DB Sessions

**What:** SQLAlchemy async sessions are created per-request via FastAPI `Depends()`, not shared globally. Each request gets its own session that is committed or rolled back atomically.

**When to use:** Always. This is the standard pattern for SQLAlchemy + FastAPI.

**Trade-offs:**
- Pro: Transactions are scoped to a request; no cross-request state pollution
- Pro: Easy to override in tests (inject a test session)
- Con: Background tasks that outlive the request must receive the session explicitly — do not pass a request-scoped session into a background task; create a new one

**Example:**
```python
# database.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

engine = create_async_engine(settings.database_url)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session

# In background task — create a fresh session, don't reuse request session
async def process(from_number: str, text: str):
    async with AsyncSessionLocal() as session:
        async with session.begin():
            ...
```

### Pattern 3: Single GPT Call for Classify + Extract

**What:** The OpenAI call asks GPT to both classify the message (job vs. worker goal) and extract the structured fields in one response. The prompt instructs GPT to return a discriminated union JSON object with a `type` field and type-specific fields.

**When to use:** Always for this project — the PROJECT.md explicitly specifies this to reduce latency and token cost.

**Trade-offs:**
- Pro: One network round-trip instead of two
- Pro: Classification can inform extraction in the same context window
- Con: Prompt engineering complexity — must handle malformed responses
- Con: Pydantic validation of the response becomes critical; must handle GPT hallucinating fields

**Example schema:**
```python
# schemas/extraction.py
from pydantic import BaseModel
from typing import Literal, Union

class JobExtraction(BaseModel):
    type: Literal["job"]
    description: str
    location: str
    pay_rate: float
    estimated_duration_hours: float | None = None
    ideal_datetime: str | None = None
    datetime_flexibility: str | None = None

class WorkerExtraction(BaseModel):
    type: Literal["worker_goal"]
    target_earnings: float
    target_timeframe_days: int

class UnknownMessage(BaseModel):
    type: Literal["unknown"]
    reason: str

ExtractionResult = Union[JobExtraction, WorkerExtraction, UnknownMessage]
```

### Pattern 4: Repository with Earnings Math Query

**What:** The matching query lives entirely in `JobRepository.find_matching()` as a SQLAlchemy ORM query with a filter expression. The `MatchService` calls the repository and then applies Python-level sorting if needed.

**When to use:** For v1 earnings math. The filter `pay_rate * estimated_duration_hours >= target_earnings` can be expressed as a SQLAlchemy column expression directly.

**Trade-offs:**
- Pro: Logic stays in the database, which scales better than Python-side filtering
- Pro: Single query returns only matching jobs, not all jobs
- Con: `estimated_duration_hours` may be NULL — must handle with COALESCE or filter nulls
- Con: SQL arithmetic on floats can produce floating-point edge cases — consider using `Numeric` type in Postgres

## Data Flow

### Inbound Job Posting Flow

```
Twilio POST /webhook/sms
    │ (From=+1234, Body="Need electrician tomorrow 9am...")
    ▼
Webhook route validates Twilio signature
    │
    ▼
Returns empty TwiML <Response> (HTTP 200 immediately)
    │
    ▼ (background task)
MessageService.process(from="+1234", text="...")
    │
    ├──► PhoneRepository.get_or_create("+1234")
    │         └──► phones table (upsert)
    │
    ├──► ExtractionService.classify_and_extract(text)
    │         └──► OpenAI GPT API
    │              └──► Returns JobExtraction JSON
    │              └──► Pydantic validates response
    │
    ├──► JobRepository.create(job_data, phone_id)
    │         └──► jobs table (INSERT with pgvector embedding=NULL for now)
    │
    └──► Twilio REST API: send confirmation SMS to "+1234"
              └──► "Got it! Job posted: Electrician, $X/hr, [date]"
```

### Inbound Worker Goal Flow

```
Twilio POST /webhook/sms
    │ (From=+1555, Body="I need to make $500 this week")
    ▼
Webhook route validates Twilio signature
    │
    ▼
Returns empty TwiML <Response> (HTTP 200 immediately)
    │
    ▼ (background task)
MessageService.process(from="+1555", text="...")
    │
    ├──► PhoneRepository.get_or_create("+1555")
    │
    ├──► ExtractionService.classify_and_extract(text)
    │         └──► OpenAI GPT API
    │              └──► Returns WorkerExtraction JSON
    │
    ├──► WorkerRepository.create(worker_data, phone_id)
    │
    ├──► MatchService.find_matches(target_earnings=500, timeframe_days=7)
    │         └──► JobRepository.find_matching(earnings_needed=500)
    │              └──► SQL: WHERE pay_rate * duration_hours >= 500
    │              └──► ORDER BY ideal_datetime ASC, duration_hours ASC
    │
    └──► Twilio REST API: send ranked jobs SMS to "+1555"
              └──► "3 jobs match: 1) Electrician $600, tomorrow 9am..."
```

### Key Data Flows

1. **Identity resolution:** Every inbound message starts with `PhoneRepository.get_or_create()`. Phone number is the only identity token. First text auto-registers.
2. **GPT response validation:** `ExtractionService` must always validate GPT output through Pydantic before any downstream use. Never trust raw GPT JSON.
3. **Outbound SMS path:** Confirmation/reply SMS is always sent via the Twilio REST API client (not TwiML), because it happens in a background task after the webhook has already responded.
4. **Embedding flow (v1 schema only):** The `jobs.embedding` column exists in the schema (vector type) but is NULL in v1. No embedding generation happens in v1. This preserves the schema for future semantic search without a migration.

## Async / Sync Tradeoffs

| Decision | Choice | Rationale |
|----------|--------|-----------|
| FastAPI mode | `async def` routes | Allows non-blocking I/O for DB + OpenAI calls |
| SQLAlchemy | `asyncpg` driver + async session | Non-blocking DB I/O; pairs with `create_async_engine` |
| OpenAI calls | `openai` async client (`AsyncOpenAI`) | Non-blocking; required when using `async def` handlers |
| Twilio outbound | `twilio` REST client (sync) in thread or `httpx` async | Official `twilio` SDK is sync; wrap in `asyncio.to_thread()` or use raw `httpx` |
| Twilio signature validation | Sync (pure computation) | No I/O; fine to call synchronously in a FastAPI `Depends` |
| Business logic (MatchService) | Sync pure functions | No I/O; async adds noise without benefit |

**Critical note on Twilio SDK:** The official `twilio-python` SDK's REST client uses `requests` (sync). Calling it directly inside `async def` will block the event loop. Two options:
- Wrap in `asyncio.to_thread(client.messages.create, ...)` — simplest
- Use `httpx` directly with the Twilio REST API — more control, fully async

For MVP, `asyncio.to_thread()` is the pragmatic choice.

## Migration Tooling (Alembic)

**Pattern:** Alembic with `async` support via `run_sync` in `env.py`.

```
alembic/
├── env.py          # Async engine setup; uses asyncio.run() + conn.run_sync(do_run_migrations)
└── versions/       # Auto-generated migration files

Commands:
  alembic revision --autogenerate -m "create jobs table"
  alembic upgrade head
  alembic downgrade -1
```

**pgvector in migrations:** The `CREATE EXTENSION vector` must run before any `vector` column is created. Add it to the initial migration with `op.execute("CREATE EXTENSION IF NOT EXISTS vector")`.

**ORM model for vector column:**
```python
from pgvector.sqlalchemy import Vector
embedding: Mapped[Optional[list[float]]] = mapped_column(Vector(1536), nullable=True)
```

**Docker startup order:** `alembic upgrade head` must run after postgres is healthy but before the app accepts traffic. Use a `command` override or entrypoint script in docker-compose.

## Docker Setup

```yaml
# docker-compose.yml
services:
  postgres:
    image: pgvector/pgvector:pg16   # Official pgvector image — no manual EXTENSION install
    environment:
      POSTGRES_DB: vici
      POSTGRES_USER: vici
      POSTGRES_PASSWORD: vici
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U vici"]
      interval: 5s
      timeout: 5s
      retries: 5

  app:
    build: .
    depends_on:
      postgres:
        condition: service_healthy
    command: >
      sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"
    environment:
      DATABASE_URL: postgresql+asyncpg://vici:vici@postgres:5432/vici
      OPENAI_API_KEY: ${OPENAI_API_KEY}
      TWILIO_ACCOUNT_SID: ${TWILIO_ACCOUNT_SID}
      TWILIO_AUTH_TOKEN: ${TWILIO_AUTH_TOKEN}
```

**Dockerfile pattern:** Multi-stage is not needed for MVP. Use a single stage with `python:3.12-slim`.

## Observability

**Structured logging over print statements:**
Use `structlog` for structured JSON logs. Every log entry should include `phone_number`, `message_type`, and `request_id` as context fields. This enables log aggregation (Datadog, CloudWatch, etc.) without code changes.

```python
import structlog
log = structlog.get_logger()

# In MessageService:
log.info("message_classified", phone=from_number, type=result.type)
log.error("gpt_extraction_failed", phone=from_number, error=str(e))
```

**Request ID propagation:** Generate a UUID per webhook request and thread it through service and repository calls via Python `contextvars`. This links all log lines for a single SMS interaction.

**Health endpoint:** Add `GET /health` that checks DB connectivity. Required for Docker healthchecks and any future load balancer.

**Error surfaces:**
- GPT API errors: log + send "Sorry, we couldn't process your message. Try again." via Twilio REST
- DB errors: log + same fallback SMS
- Twilio signature validation failures: return HTTP 403 (do not send SMS)
- Pydantic validation failures on GPT response: log raw GPT output + fallback SMS

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 0-1k messages/day | Single FastAPI process, single Postgres instance, no queue — monolith is fine |
| 1k-50k messages/day | Add connection pooling (`PgBouncer` or SQLAlchemy pool tuning); scale uvicorn workers |
| 50k+ messages/day | Move GPT calls into a task queue (Celery + Redis or ARQ); webhook returns TwiML ack and queue processes async; consider read replicas for matching queries |

**First bottleneck:** OpenAI API latency (1-5 seconds per call). At high volume this becomes the limiting factor. The background task pattern already decouples it from Twilio's response window — the next step is a proper task queue to handle bursts.

**Second bottleneck:** Postgres connection exhaustion under high concurrency. SQLAlchemy's async engine pool defaults (5 connections) need tuning before this, or PgBouncer in front of Postgres.

## Anti-Patterns

### Anti-Pattern 1: Business Logic in Routes

**What people do:** Put the earnings math, GPT call, or DB queries directly in the webhook route handler.
**Why it's wrong:** Makes the route untestable without a full HTTP stack; logic cannot be reused; violates the PROJECT.md requirement for layered architecture.
**Do this instead:** Routes call `message_service.process()` and return. All logic lives in services and repositories.

### Anti-Pattern 2: Passing Request-Scoped DB Session to Background Tasks

**What people do:** `background_tasks.add_task(process, session=db_session)` where `db_session` was created by the request's `Depends(get_session)`.
**Why it's wrong:** The session is closed when the request handler returns. The background task runs after — using a closed session raises `sqlalchemy.exc.InvalidRequestError`.
**Do this instead:** Background tasks create their own sessions using `AsyncSessionLocal()` directly.

### Anti-Pattern 3: Trusting Raw GPT JSON Without Validation

**What people do:** `result = json.loads(gpt_response)` and pass the dict directly to repository.
**Why it's wrong:** GPT hallucinates field names, types, and structure. Missing required fields cause KeyErrors deep in the stack; wrong types cause DB write failures.
**Do this instead:** Always parse GPT response through the Pydantic `ExtractionResult` discriminated union. Catch `ValidationError` and handle gracefully (log + fallback SMS).

### Anti-Pattern 4: Storing pgvector as a Python List Without the Extension

**What people do:** Use a plain `ARRAY` column or a JSON column for embeddings instead of `pgvector`'s `vector` type, planning to "switch later."
**Why it's wrong:** Retrofitting `vector` type requires a migration, data backfill, and the `pgvector/pgvector` Docker image. The PROJECT.md explicitly front-loads this to avoid it.
**Do this instead:** Use the `pgvector/pgvector:pg16` Docker image from day one and define the `embedding` column as `Vector(1536)` even if it stays NULL in v1.

### Anti-Pattern 5: Synchronous Twilio SDK in Async Handler Without Thread Isolation

**What people do:** Call `client.messages.create(...)` directly inside an `async def` function.
**Why it's wrong:** The `twilio` SDK uses `requests` (blocking). This blocks the asyncio event loop for the duration of the HTTP call, degrading all concurrent requests.
**Do this instead:** `await asyncio.to_thread(client.messages.create, to=..., from_=..., body=...)`.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Twilio inbound webhook | FastAPI route receives `application/x-www-form-urlencoded` POST | Validate `X-Twilio-Signature` header using `twilio.request_validator.RequestValidator` |
| Twilio outbound SMS | Twilio REST API via `twilio` SDK (sync) wrapped in `asyncio.to_thread()` | Runs in background task, not in the webhook response path |
| OpenAI GPT API | `openai.AsyncOpenAI` client, `chat.completions.create()` with JSON mode | Use `response_format={"type": "json_object"}` to enforce JSON output |
| PostgreSQL + pgvector | `asyncpg` driver via SQLAlchemy async engine | Use `pgvector/pgvector:pg16` Docker image; `CREATE EXTENSION vector` in initial Alembic migration |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Route → Service | Direct function call, passes `from_number: str`, `text: str`, `session: AsyncSession` | Route never inspects service return value beyond success/error |
| Service → Repository | Direct method call, passes `session: AsyncSession` | Session always flows down; never created by repositories |
| Service → ExtractionService | Direct async method call; returns validated Pydantic model | Services do not handle raw GPT JSON |
| Service → MatchService | Direct method call; returns `list[JobSchema]` | MatchService is pure logic; no I/O |
| Repository → DB | SQLAlchemy ORM async queries | No raw SQL strings except in complex vector queries |

## Suggested Build Order

The following order respects layer dependencies (infrastructure before domain, domain before integration):

1. **Infrastructure foundation** — Docker Compose (postgres + pgvector), Alembic setup, `database.py`, `config.py`, health endpoint. Everything else depends on a running DB.
2. **Data models + migrations** — SQLAlchemy ORM models for `phone_numbers`, `jobs`, `workers`; Alembic initial migration including `CREATE EXTENSION vector`.
3. **Repository layer** — `PhoneRepository`, `JobRepository`, `WorkerRepository` with basic CRUD. Testable against a real test DB.
4. **Extraction service** — `ExtractionService` calling OpenAI, returning validated Pydantic schemas. Testable with mocked OpenAI responses.
5. **Match service** — `MatchService.find_matches()` + `JobRepository.find_matching()` earnings query. Testable with seeded DB data.
6. **Message orchestration** — `MessageService.process()` wiring classify → extract → store → match → reply.
7. **Webhook route + Twilio integration** — POST `/webhook/sms`, signature validation, background task wiring, TwiML response, outbound SMS.
8. **Observability** — Structured logging, request ID propagation, error handling, fallback SMS responses.

## Sources

- FastAPI official docs: https://fastapi.tiangolo.com/tutorial/bigger-applications/ (HIGH confidence — stable pattern)
- SQLAlchemy async docs: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html (HIGH confidence)
- pgvector Python: https://github.com/pgvector/pgvector-python (HIGH confidence)
- Alembic async env.py pattern: https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic (HIGH confidence)
- Twilio Python SDK: https://www.twilio.com/docs/libraries/python (HIGH confidence)
- Twilio webhook security: https://www.twilio.com/docs/usage/security (HIGH confidence)
- OpenAI Python async client: https://platform.openai.com/docs/api-reference (HIGH confidence)

Note: WebSearch and WebFetch were unavailable during this research session. All findings draw from training knowledge of mature, well-documented libraries (FastAPI 0.100+, SQLAlchemy 2.0, Alembic 1.x, twilio-python 8.x, openai-python 1.x, pgvector 0.2+). Confidence is HIGH for architectural patterns because these are stable conventions unlikely to have changed fundamentally.

---
*Architecture research for: SMS webhook + AI extraction + job matching API (Vici)*
*Researched: 2026-03-05*
