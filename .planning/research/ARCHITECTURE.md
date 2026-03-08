# Architecture Research

**Domain:** SMS webhook + AI extraction + job matching API
**Researched:** 2026-03-08
**Confidence:** HIGH — derived from the actual built system (Phases 01–02.5 complete). Source: STATE.md, PROJECT.md, REQUIREMENTS.md.

## Standard Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                            EXTERNAL                                   │
│  ┌──────────────┐                         ┌──────────────────────┐   │
│  │ Twilio SMS   │ POST /webhook/sms        │  OpenAI GPT API      │   │
│  │ (inbound)    │ ────────────────────►   │  (classify+extract)  │   │
│  └──────────────┘                         └──────────────────────┘   │
│  ┌──────────────┐                         ┌──────────────────────┐   │
│  │ Pinecone     │ ◄── job embeddings       │  Inngest Cloud       │   │
│  │ (vector DB)  │                          │  (async functions)   │   │
│  └──────────────┘                         └──────────────────────┘   │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ webhook payload
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    API LAYER (FastAPI + lifespan DI)                   │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │  POST /webhook/sms  — 5-gate security chain:                   │   │
│  │  1. Twilio signature validation (HTTPException 403 on failure) │   │
│  │  2. MessageSid idempotency check (unique constraint)           │   │
│  │  3. User get-or-create (phone_hash)                            │   │
│  │  4. Rate limit check (raw SQL, bypasses ORM cache)             │   │
│  │  5. Persist message to messages table                          │   │
│  │     └── Inngest event emit (message.received) → HTTP 200       │   │
│  └────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ Inngest event
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│         INNGEST FUNCTION LAYER (process-message, 3 retries)           │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │  PipelineOrchestrator.run()                                     │   │
│  │  ├── Job branch: ExtractionService → JobRepository flush        │   │
│  │  │                → write_job_embedding() → Pinecone            │   │
│  │  ├── WorkRequest branch: ExtractionService                      │   │
│  │  │                → WorkRequestRepository flush → commit         │   │
│  │  └── Unknown branch: asyncio.to_thread(twilio.messages.create) │   │
│  └────────────────────────────────────────────────────────────────┘   │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │  sync-pinecone-queue cron (*/5 * * * *)                         │   │
│  │  Sweeps pinecone_sync_queue (max 50/run), retries embeddings    │   │
│  └────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                          DATA LAYER                                    │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │  PostgreSQL 16 (plain)                                          │   │
│  │  Tables: users, messages, jobs, work_requests,                  │   │
│  │          rate_limit, audit_log, matches, pinecone_sync_queue    │   │
│  │  No vector column — Pinecone is the external vector store       │   │
│  └────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Actual Module |
|-----------|----------------|---------------|
| Webhook route | 5-gate security chain (sig validate, idempotency, user, rate limit, persist), Inngest event emit, return HTTP 200 | `src/sms/router.py` |
| PipelineOrchestrator | Full pipeline (Job / WorkRequest / Unknown branches), single commit per branch, Pinecone write, graceful unknown reply | `src/extraction/pipeline.py` |
| ExtractionService | Single GPT call via `beta.chat.completions.parse` returning `JobExtraction | WorkerExtraction | UnknownMessage` discriminated union | `src/extraction/service.py` |
| MatchService | ⏳ Phase 3 — earnings math SQL + ranked SMS formatter (placeholder exists) | `src/matches/` |
| MessageRepository | get-or-create user by phone_hash, persist message, dedup check | `src/sms/repository.py` |
| AuditLogRepository | Store raw SMS body + raw GPT response per message | `src/sms/repository.py` |
| JobRepository | CRUD for job records + ⏳ Phase 3 matching query | `src/jobs/repository.py` |
| WorkRequestRepository | CRUD for work_request records | `src/work_requests/repository.py` |
| inngest_client | `process-message` function (3 retries, on_failure) + `sync-pinecone-queue` cron; module-level `_orchestrator` var set by lifespan | `src/inngest_client.py` |
| metrics | Prometheus metric singletons (imported lazily inside functions to avoid circular imports) | `src/metrics.py` |
| Alembic migrations | Schema versioning — asyncio.run() pattern in env.py | `alembic/` |
| Settings | Nested Pydantic Settings (4 sub-models: db, twilio, openai, observability) via model_validator(mode=after) | `src/config.py` |
| Observability | structlog JSON + OTel ALWAYS_ON sampler → Jaeger v2 (OpenSearch) + Prometheus → Grafana | Multiple modules |

## Recommended Project Structure

```
src/
├── main.py                    # FastAPI app + lifespan DI graph
├── config.py                  # Nested Pydantic Settings (4 sub-models)
├── database.py                # Async SQLAlchemy engine + sessionmaker
├── models.py                  # Central SQLModel aggregator
├── inngest_client.py          # process-message + sync-pinecone-queue Inngest functions
├── metrics.py                 # Prometheus metric singletons
├── exceptions.py              # Custom exceptions
├── sms/                       # Webhook route, MessageRepository, AuditLogRepository
├── extraction/                # ExtractionService, PipelineOrchestrator, schemas, pinecone_client
├── jobs/                      # JobRepository, Job SQLModel
├── work_requests/             # WorkRequestRepository, WorkRequest SQLModel
├── users/                     # User SQLModel
└── matches/                   # Match SQLModel (placeholder, Phase 3)

alembic/
├── env.py          # Async engine setup; uses asyncio.run() + conn.run_sync(do_run_migrations)
└── versions/       # Auto-generated migration files

tests/
├── conftest.py             # Fixtures: SQLite test DB, mock Twilio, mock OpenAI, _auto_mock_inngest_send
├── sms/
│   └── test_webhook.py
├── extraction/
│   └── test_pipeline.py
└── ...
```

### Structure Rationale

- **src/ (flat domain modules):** Each domain (sms, extraction, jobs, work_requests, users, matches) owns its router, repository, and SQLModel. No api/v1/routes/ indirection — the single webhook is the only HTTP surface.
- **src/inngest_client.py:** Module-level `_orchestrator` and `_openai_client` vars set by FastAPI lifespan — cleanest circular import avoidance pattern for Inngest functions that need DI-injected objects.
- **src/extraction/pipeline.py:** PipelineOrchestrator owns all pipeline logic (Job/WorkRequest/Unknown branches); ExtractionService owns GPT-only logic. Clean separation.
- **src/models.py:** Central SQLModel aggregator — imports all ORM models so Alembic autogenerate sees the full schema in one import.

## Architectural Patterns

### Pattern 1: Inngest Event-Driven Processing (Implemented)

**What:** The webhook route returns HTTP 200 to Twilio immediately after emitting an Inngest `message.received` event. All GPT processing, storage, and Pinecone writes happen inside the `process-message` Inngest function — outside Twilio's response window.

**When to use:** Always (this is the implemented pattern).

**Trade-offs:**
- Pro: Eliminates webhook timeout risk — Twilio sees HTTP 200 within milliseconds
- Pro: Inngest handles retries (3 configured) with on_failure handler
- Pro: Pinecone failure doesn't rollback PostgreSQL transaction
- Con: Debugging requires checking Inngest function logs, not just the webhook

**Example:**
```python
# Actual pattern — src/sms/router.py
@router.post("/webhook/sms")
async def handle_sms(request: Request, ...):
    # 5-gate chain runs synchronously in webhook handler
    await emit_message_received_event(message_id=message.id, sms_text=body)
    return Response(status_code=200)

# Inngest function — src/inngest_client.py
@inngest_client.create_function(
    fn_id="process-message",
    trigger=inngest.TriggerEvent(event="message/received"),
    retries=3,
    on_failure=_handle_process_message_failure,
)
async def process_message(ctx, step):
    await _orchestrator.run(ctx.event.data["message_id"])
```

### Pattern 2: Dependency Injection for DB Sessions

**What:** SQLAlchemy async sessions are created per-request via FastAPI `Depends()` for webhook handlers. Inngest functions create their own sessions via the module-level session factory — they are NOT FastAPI request handlers and cannot use `Depends`.

**When to use:** Always for both contexts.

**Trade-offs:**
- Pro: Transactions are scoped to a request; no cross-request state pollution
- Pro: Easy to override in tests (inject a test session)
- Con: Module-level `_orchestrator` var in `inngest_client.py` is set by FastAPI lifespan — cleanest circular import avoidance

**Example:**
```python
# database.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

engine = create_async_engine(settings.database_url)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session

# In Inngest function — create a fresh session directly (not via Depends)
async def process_message(ctx, step):
    async with async_session_factory() as session:
        await _orchestrator.run(ctx.event.data["message_id"], session)
```

`expire_on_commit=False` is required for async; otherwise accessing attributes after `commit()` triggers a lazy-load which fails outside a session context.

### Pattern 3: Single GPT Call for Classify + Extract

**What:** The OpenAI call asks GPT to both classify the message (job vs. worker goal) and extract the structured fields in one response. Uses `beta.chat.completions.parse` with a Pydantic discriminated union `response_format`.

**When to use:** Always for this project — reduces latency and token cost.

**Trade-offs:**
- Pro: One network round-trip instead of two
- Pro: Classification can inform extraction in the same context window
- Con: Prompt engineering complexity — must handle malformed responses

**Example schema:**
```python
# src/extraction/schemas.py
from pydantic import BaseModel
from typing import Literal, Union, Annotated
from pydantic import Field

class JobExtraction(BaseModel):
    type: Literal["job"]
    description: str
    location: str
    pay_rate: float
    estimated_duration_hours: float | None = None

class WorkerExtraction(BaseModel):
    type: Literal["worker_goal"]
    target_earnings: float
    target_timeframe_days: int

class UnknownMessage(BaseModel):
    type: Literal["unknown"]
    reason: str

ExtractionResult = Annotated[
    Union[JobExtraction, WorkerExtraction, UnknownMessage],
    Field(discriminator="type")
]
```

### Pattern 4: Repository with Earnings Math Query (Phase 3)

**What:** ⏳ Phase 3 — The matching query will live in `JobRepository` as a SQLAlchemy ORM query. `MatchService` calls the repository and formats the ranked SMS reply.

**When to use:** Phase 3 implementation.

## Data Flow

### Inbound Job Posting Flow

```
Twilio POST /webhook/sms
    │
    ▼ 5-gate chain
MessageRepository.get_or_create(phone_hash) → users table
MessageRepository.create(message) → messages table
AuditLogRepository.create(raw_body) → audit_log table
emit_message_received_event(message_id) → Inngest
    │ HTTP 200 returned to Twilio here
    ▼ (Inngest function, async)
PipelineOrchestrator.run(message_id)
    ├── ExtractionService.process() → OpenAI beta.chat.completions.parse
    │       └── Returns JobExtraction (discriminated union)
    ├── JobRepository.create(job) → session.flush() (no commit yet)
    ├── session.commit() (single commit for the branch)
    └── write_job_embedding(job.id) → Pinecone upsert
              └── on failure: pinecone_sync_queue INSERT (separate session)
```

### Inbound Worker Goal Flow

```
Twilio POST /webhook/sms
    │
    ▼ 5-gate chain
MessageRepository.get_or_create(phone_hash) → users table
MessageRepository.create(message) → messages table
AuditLogRepository.create(raw_body) → audit_log table
emit_message_received_event(message_id) → Inngest
    │ HTTP 200 returned to Twilio here
    ▼ (Inngest function, async)
PipelineOrchestrator.run(message_id)
    ├── ExtractionService.process() → OpenAI beta.chat.completions.parse
    │       └── Returns WorkerExtraction (discriminated union)
    ├── WorkRequestRepository.create(work_request) → session.flush()
    ├── session.commit()
    └── ⏳ Phase 3: MatchService.find_matches() → ranked SMS reply via Twilio
```

### Key Data Flows

1. **Identity resolution:** Every inbound message starts with `MessageRepository.get_or_create(phone_hash)`. Phone number hashed to phone_hash — the only identity token. First text auto-registers.
2. **GPT response validation:** `ExtractionService` uses `beta.chat.completions.parse` — OpenAI validates the response against the Pydantic schema before returning. Never trust raw GPT JSON.
3. **Outbound SMS path:** Unknown-branch reply sent via `asyncio.to_thread(twilio_client.messages.create)` inside PipelineOrchestrator — Twilio SDK is sync, must be wrapped.
4. **Pinecone write path:** After JobRepository.create() flush and session.commit(), `write_job_embedding()` fires. On Pinecone failure, a separate session inserts into `pinecone_sync_queue`. Inngest cron `sync-pinecone-queue` sweeps queue every 5 minutes (max 50/run). No vector column in PostgreSQL.

## Async / Sync Tradeoffs

| Decision | Choice | Rationale |
|----------|--------|-----------|
| FastAPI mode | `async def` routes | Allows non-blocking I/O for DB + OpenAI calls |
| SQLAlchemy | `asyncpg` driver + async session | Non-blocking DB I/O; pairs with `create_async_engine` |
| OpenAI calls | `openai` async client (`AsyncOpenAI`) | Non-blocking; required when using `async def` handlers |
| Twilio outbound | `twilio` REST client (sync) in `asyncio.to_thread()` | Official `twilio` SDK is sync; wrap in `asyncio.to_thread()` |
| Twilio signature validation | Sync (pure computation) | No I/O; fine to call synchronously in a FastAPI `Depends` |
| Business logic (PipelineOrchestrator branches) | Async | Coordinates async DB sessions and Pinecone writes |

**Critical note on Twilio SDK:** The official `twilio-python` SDK's REST client uses `requests` (sync). Calling it directly inside `async def` will block the event loop. Use `await asyncio.to_thread(client.messages.create, ...)`.

## Migration Tooling (Alembic)

**Pattern:** Alembic with `async` support via `asyncio.run()` in `env.py`.

```
alembic/
├── env.py          # Async engine setup; uses asyncio.run() + conn.run_sync(do_run_migrations)
└── versions/       # Auto-generated migration files

Commands:
  alembic revision --autogenerate -m "create jobs table"
  alembic upgrade head
  alembic downgrade -1
```

**Note:** postgres:16 plain image is used — no vector extension, no vector column. Pinecone is the external vector store. No `CREATE EXTENSION vector` in migrations.

**Docker startup order:** `alembic upgrade head` must run after postgres is healthy but before the app accepts traffic. The render.yaml pre-deploy hook handles this in production (PROD-04 complete).

## Docker Setup

```yaml
# docker-compose.yml — 8 services
services:
  postgres:
    image: postgres:16  # plain — no vector extension
  opensearch:
    image: opensearchproject/opensearch:2.19.4
  jaeger-collector:    # Jaeger v2 with OTLP gRPC receiver
  jaeger-query:        # Jaeger v2 query/UI service
  app:
    build: .           # Multi-stage Dockerfile; non-root appuser
  inngest:             # Inngest Dev Server
  prometheus:          # Auto-provisioned via config/prometheus.yml
  grafana:             # Auto-provisioned with FastAPI dashboard
```

Note: Multi-stage Dockerfile is implemented (PROD-01): builder stage (uv sync) + runtime stage (non-root appuser, HEALTHCHECK on /health).

## Observability

Implemented observability stack:
- structlog JSON structured logging — phone_hash, message_id, trace_id on every request (OBS-04)
- OpenTelemetry ALWAYS_ON sampler → OTLP gRPC → Jaeger v2 collector → OpenSearch 2.19.4 (OBS-03)
  - Manual spans: Inngest function, GPT call, Pinecone upsert, Twilio SMS
- Prometheus /metrics endpoint — request count, latency histograms, error rates, GPT token counters,
  latency histogram, pinecone_sync_queue depth gauge (OBS-02)
- Grafana pre-built FastAPI dashboard, auto-provisioned from Docker Compose (OBS-02)
- Braintrust LLM observability — wraps AsyncOpenAI via wrap_openai (OBS-01)

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 0-1k messages/day | Single FastAPI process, single Postgres instance, Inngest cloud — monolith is fine |
| 1k-50k messages/day | Add connection pooling (`PgBouncer` or SQLAlchemy pool tuning); scale uvicorn workers |
| 50k+ messages/day | Inngest function concurrency limits; consider dedicated Inngest worker nodes; Postgres read replicas for matching queries |

**First bottleneck:** OpenAI API latency (1-5 seconds per call). Inngest already decouples this from Twilio's response window — the next step is Inngest concurrency tuning.

**Second bottleneck:** Postgres connection exhaustion under high concurrency. SQLAlchemy's async engine pool defaults need tuning, or PgBouncer in front of Postgres.

## Anti-Patterns

### Anti-Pattern 1: Business Logic in Routes

**What people do:** Put the earnings math, GPT call, or DB queries directly in the webhook route handler.
**Why it's wrong:** Makes the route untestable without a full HTTP stack; logic cannot be reused.
**Do this instead:** Routes run the 5-gate chain and emit the Inngest event. All pipeline logic lives in PipelineOrchestrator.

### Anti-Pattern 2: Passing Request-Scoped DB Session to Inngest Functions

**What people do:** Attempt to pass the FastAPI `Depends(get_session)` session into an Inngest function.
**Why it's wrong:** Inngest functions are not FastAPI request handlers — they cannot use `Depends()`. The session would be out of scope.
**Do this instead:** Inngest functions create their own sessions using `async_session_factory()` directly.

### Anti-Pattern 3: Trusting Raw GPT JSON Without Validation

**What people do:** `result = json.loads(gpt_response)` and pass the dict directly to repository.
**Why it's wrong:** GPT hallucinates field names, types, and structure. Missing required fields cause KeyErrors deep in the stack.
**Do this instead:** Use `beta.chat.completions.parse` with Pydantic `ExtractionResult` discriminated union. Catch `ValidationError` and handle gracefully.

### Anti-Pattern 4: Module-Level DI Vars Set at Import Time

**What:** Setting `_orchestrator = PipelineOrchestrator(...)` at module top-level in `inngest_client.py`.
**Why wrong:** FastAPI lifespan hasn't run yet; dependencies (DB engine, OpenAI client) aren't initialized.
**Do this instead:** Set `_orchestrator = None` at module level; set it inside `app.lifespan()` after building the DI graph.

### Anti-Pattern 5: Synchronous Twilio SDK in Async Handler Without Thread Isolation

**What people do:** Call `client.messages.create(...)` directly inside an `async def` function.
**Why it's wrong:** The `twilio` SDK uses `requests` (blocking). This blocks the asyncio event loop for the duration of the HTTP call.
**Do this instead:** `await asyncio.to_thread(client.messages.create, to=..., from_=..., body=...)`.

### Anti-Pattern 6: OpenSearch Replicas > 0 on Single-Node

**What:** Leaving default `number_of_replicas: 1` in the OpenSearch index template.
**Why wrong:** Single-node OpenSearch can't allocate replica shards → index health stays yellow → Jaeger index creation fails.
**Do this instead:** Set `number_of_replicas: 0` in the index template for local dev.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Twilio inbound webhook | FastAPI route receives `application/x-www-form-urlencoded` POST | Validate `X-Twilio-Signature` header using `twilio.request_validator.RequestValidator` |
| Twilio outbound SMS | Twilio REST API via `twilio` SDK (sync) wrapped in `asyncio.to_thread()` | Runs inside PipelineOrchestrator unknown branch, not in the webhook response path |
| OpenAI GPT API | `openai.AsyncOpenAI` client, `beta.chat.completions.parse()` with Pydantic model | Structured outputs via discriminated union — no raw JSON parsing |
| Pinecone | `pinecone-client` SDK | `text-embedding-3-small` (1536 dims); job embeddings at creation time; failures queued in `pinecone_sync_queue` |
| Inngest | `inngest` Python SDK | `process-message` function (3 retries) + `sync-pinecone-queue` cron (*/5 * * * *) |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Route → Inngest | `emit_message_received_event(message_id)` | Route never passes DB objects to Inngest; only the message_id |
| Inngest → PipelineOrchestrator | `_orchestrator.run(message_id)` | Module-level var set by lifespan |
| PipelineOrchestrator → ExtractionService | Direct async method call; returns validated Pydantic union | ExtractionService owns only GPT logic |
| PipelineOrchestrator → Repositories | Direct method calls, passes `session: AsyncSession` | Session always flows down; never created by repositories |
| Repository → DB | SQLAlchemy ORM async queries | Raw SQL only for rate_limit check (bypass ORM identity cache) |

## Implemented vs. Pending Status

All infrastructure and extraction phases (01–02.5) are complete:
- ✅ Phase 01: Schema, migrations, webhook security chain
- ✅ Phase 01.1: 3NF schema refactor (User/Message/Job/WorkRequest)
- ✅ Phase 02: GPT extraction service, PipelineOrchestrator, Pinecone
- ✅ Phase 02.1: Service boundary refactor, DI graph, Inngest functions
- ✅ Phase 02.3: OTel → Jaeger v2, OpenSearch
- ✅ Phase 02.4: Prometheus metrics, Grafana dashboard
- ✅ Phase 02.5: Production hardening (Dockerfile, render.yaml, CI)

Pending:
- ⏳ Phase 3: MatchService (earnings math SQL, ranked SMS formatter, empty-match fallback) — `src/matches/`
- ⏳ Phase 4: Outbound SMS for job posters and workers, STOP/START pass-through, Render.com production deploy

## Sources

PRIMARY: STATE.md, PROJECT.md, REQUIREMENTS.md (HIGH confidence — derived from built system, 2026-03-08)

- FastAPI official docs: https://fastapi.tiangolo.com/tutorial/bigger-applications/ (HIGH confidence — stable pattern)
- SQLAlchemy async docs: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html (HIGH confidence)
- Alembic async env.py pattern: https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic (HIGH confidence)
- Twilio Python SDK: https://www.twilio.com/docs/libraries/python (HIGH confidence)
- Twilio webhook security: https://www.twilio.com/docs/usage/security (HIGH confidence)
- OpenAI Python async client: https://platform.openai.com/docs/api-reference (HIGH confidence)
- Inngest Python SDK: https://www.inngest.com/docs/sdk/serve (HIGH confidence)

---
*Architecture research for: SMS webhook + AI extraction + job matching API (Vici)*
*Researched: 2026-03-08*
