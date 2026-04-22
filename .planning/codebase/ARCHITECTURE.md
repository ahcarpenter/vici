# Architecture

**Analysis Date:** 2026-04-22

## Pattern Overview

**Overall:** Modular monolith with durable workflow orchestration

The application is a single deployable Python process (FastAPI + embedded Temporal worker). It exposes one HTTP endpoint (`POST /webhook/sms`) and runs a co-located Temporal worker coroutine within the same asyncio event loop. There are no microservices; all domain logic is in-process.

**Key Characteristics:**
- Domain-per-directory layout under `src/` (sms, jobs, work_goals, matches, extraction, pipeline, temporal, users)
- Temporal used for durable, retryable message processing — not for workflow decomposition across services
- Chain of Responsibility pattern for SMS classification dispatch (`pipeline/`)
- Repository pattern with a shared `BaseRepository` flush-only base class
- All monetary values stored and passed internally as integer cents; dollar conversion only at extraction and SMS output boundaries
- OpenTelemetry traces propagated from FastAPI → SQLAlchemy → Temporal worker via TracingInterceptor

---

## High-Level ASCII Diagram

```
Twilio
  │
  ▼ POST /webhook/sms
┌─────────────────────────────────┐
│   FastAPI (src/main.py)         │
│                                 │
│  Dependency Chain (sms/deps)    │
│  1. validate_twilio_request     │
│  2. check_idempotency           │
│  3. get_or_create_user          │
│  4. enforce_rate_limit          │
│         │                       │
│  sms/router.py                  │
│  1. persist Message row         │
│  2. write audit_log 'received'  │
│  3. emit_message_received_event─┼──────────────────────┐
└─────────────────────────────────┘                      │
                                                         ▼
                                            ┌─────────────────────────┐
                                            │  Temporal               │
                                            │  ProcessMessageWorkflow  │
                                            │         │               │
                                            │  process_message_activity│
                                            │         │               │
                                            │  PipelineOrchestrator   │
                                            │  1. ExtractionService   │
                                            │     (GPT classify)      │
                                            │  2. audit gpt_classified │
                                            │  3. Chain of Resp. ─────┤
                                            │     JobPostingHandler   │
                                            │     WorkerGoalHandler   │
                                            │     UnknownMsgHandler   │
                                            └─────────────────────────┘

Cron (every 5 min):
  SyncPineconeQueueWorkflow
    └─ sync_pinecone_queue_activity
         └─ SELECT pending from pinecone_sync_queue → upsert to Pinecone
```

---

## Layers

**HTTP Ingress (sms domain):**
- Purpose: Twilio webhook reception, pre-flight validation gates
- Location: `src/sms/router.py`, `src/sms/dependencies.py`
- Contains: FastAPI router, chained dependency gates (validation, idempotency, user upsert, rate limit)
- Depends on: `src/database.py`, `src/sms/repository.py`, `src/users/repository.py`, `src/sms/audit_repository.py`
- Used by: `src/main.py` via `app.include_router(sms_router)`

**Workflow Orchestration (temporal domain):**
- Purpose: Durable, retryable processing of inbound SMS; cron for Pinecone sync
- Location: `src/temporal/workflows.py`, `src/temporal/activities.py`, `src/temporal/worker.py`
- Contains: Two `@workflow.defn` classes, three `@activity.defn` functions, worker lifecycle
- Depends on: `src/pipeline/orchestrator.py`, `src/database.py`, `src/extraction/utils.py`
- Used by: `src/main.py` lifespan (spawned as asyncio task)

**Pipeline (pipeline domain):**
- Purpose: Classify SMS text, dispatch to appropriate domain handler via Chain of Responsibility
- Location: `src/pipeline/orchestrator.py`, `src/pipeline/handlers/`, `src/pipeline/context.py`
- Contains: `PipelineOrchestrator`, `MessageHandler` ABC, three concrete handlers, `PipelineContext` dataclass
- Depends on: `src/extraction/`, `src/jobs/`, `src/work_goals/`, `src/sms/audit_repository.py`
- Used by: `src/temporal/activities.py::process_message_activity`

**Extraction (extraction domain):**
- Purpose: GPT-based SMS classification and structured data extraction; Pinecone embedding writes
- Location: `src/extraction/service.py`, `src/extraction/utils.py`, `src/extraction/schemas.py`, `src/extraction/prompts.py`
- Contains: `ExtractionService` class, `write_job_embedding` async function, Pydantic output schemas
- Depends on: OpenAI SDK, Pinecone SDK; no DB access
- Used by: `src/pipeline/orchestrator.py`, `src/pipeline/handlers/job_posting.py`, `src/temporal/activities.py`

**Domain Repositories (jobs, work_goals, matches, users, sms):**
- Purpose: Persist and query domain entities; flush-only (caller owns transaction)
- Location: `src/jobs/repository.py`, `src/work_goals/repository.py`, `src/matches/repository.py`, `src/users/repository.py`, `src/sms/repository.py`, `src/sms/audit_repository.py`
- Contains: SQLModel + SQLAlchemy async queries; all extend `src/repository.py::BaseRepository`
- Depends on: `src/database.py`, domain `models.py`
- Used by: pipeline handlers, sms dependencies, temporal activities (sync activity only)

**Models (per-domain + global registry):**
- Purpose: SQLModel table definitions; `src/models.py` is the global import registry for Alembic
- Location: `src/jobs/models.py`, `src/work_goals/models.py`, `src/matches/models.py`, `src/sms/models.py`, `src/users/models.py`, `src/extraction/models.py`, `src/models.py`
- Contains: SQLModel table classes with SA column annotations, check constraints, FK relationships
- Depends on: `src/database.py::metadata` (naming convention)

**Infrastructure / Config:**
- Purpose: Settings injection, DB engine, metrics, money utilities
- Location: `src/config.py`, `src/database.py`, `src/metrics.py`, `src/money.py`
- Contains: Pydantic `BaseSettings` with sub-model remapping, `lru_cache`-guarded engine/settings singletons, Prometheus metric singletons, cent/dollar converters

---

## Data Flow

**Inbound SMS to Persistence:**

1. Twilio POSTs to `POST /webhook/sms` (`src/sms/router.py:24`)
2. `enforce_rate_limit` dependency chain runs sequentially: signature validation → idempotency check → user upsert → rate limit check (`src/sms/dependencies.py`)
3. Router opens explicit transaction (`session.begin()`), creates `Message` row, writes audit log `received`, commits
4. `emit_message_received_event` starts `ProcessMessageWorkflow` in Temporal — fire-and-forget (`src/sms/service.py:15`)
5. Router returns empty TwiML `<Response/>` to Twilio immediately

**Temporal Workflow to Classification to Persistence:**

1. `ProcessMessageWorkflow.run` executes `process_message_activity` with up to 4 retries (`src/temporal/workflows.py:31`)
2. Activity opens its own DB session, loads the `Message` row by `message_sid` to resolve `message_id` and `user_id` (`src/temporal/activities.py:54`)
3. `PipelineOrchestrator.run` invoked: calls `ExtractionService.process` (GPT classify, no DB) → writes audit `gpt_classified` → dispatches to first matching `MessageHandler` (`src/pipeline/orchestrator.py:29`)
4. Matching handler (e.g., `JobPostingHandler`) creates the domain record (job/work_goal), updates `message.message_type`, writes audit, then calls `session.commit()` — this is the single commit point for the whole pipeline (`src/pipeline/handlers/job_posting.py:76`, `src/pipeline/handlers/worker_goal.py:57`)
5. For job postings: after commit, `JobPostingHandler` attempts Pinecone upsert; on failure inserts to `pinecone_sync_queue` in a fresh session (`src/pipeline/handlers/job_posting.py:78-108`)
6. On activity failure after retries: `handle_process_message_failure_activity` logs and increments `pipeline_failures_total` counter (`src/temporal/activities.py:82`)

**Pinecone Sync (Cron):**

1. `SyncPineconeQueueWorkflow` runs on cron schedule (default `*/5 * * * *`) as a persistent workflow (`src/temporal/worker.py:47`)
2. `sync_pinecone_queue_activity` fetches up to 50 pending rows via raw SQL JOIN across `pinecone_sync_queue`, `job`, `user` tables (`src/temporal/activities.py:105`)
3. For each row: calls `write_job_embedding`, updates status to `success` or `failed` in separate sessions per row

**Matching (not wired into live pipeline):**

- `MatchService` (`src/matches/service.py`) and `format_match_sms` (`src/matches/formatter.py`) are fully implemented but not invoked by any workflow, activity, or route handler. The matching subsystem is dead code from the live pipeline perspective.

---

## Entry Points

**HTTP Server:**
- Location: `src/main.py:223` — `app = create_app()`
- Triggers: Uvicorn process start (via Docker CMD or `uvicorn src.main:app`)
- Responsibilities: OTEL setup, DI graph construction, Temporal worker launch, Prometheus exposure, router registration

**Temporal Worker:**
- Location: `src/temporal/worker.py:28` — `run_worker()`
- Triggers: `asyncio.create_task(run_worker(...))` in `lifespan()` (`src/main.py:169`)
- Responsibilities: Long-running coroutine blocking on `worker.run()`; processes both `ProcessMessageWorkflow` and `SyncPineconeQueueWorkflow`

**Health/Readiness:**
- `GET /health` — liveness, always 200 (`src/main.py:202`)
- `GET /readyz` — readiness, runs `SELECT 1` against DB (`src/main.py:209`)

---

## Async/Sync Boundaries

| Location | Pattern | Notes |
|---|---|---|
| All FastAPI routes and dependencies | `async def` | Non-blocking I/O throughout |
| `ExtractionService._call_with_retry` | `async def` with `await` | AsyncOpenAI client |
| `write_job_embedding` | `async def` | PineconeAsyncio context manager |
| `UnknownMessageHandler.handle` | `asyncio.to_thread(twilio_client.messages.create)` | Sync Twilio SDK wrapped in threadpool (`src/pipeline/handlers/unknown.py:45`) |
| Temporal Worker | `asyncio.create_task(run_worker(...))` | Co-runs with FastAPI event loop; shares event loop |
| `_update_gauges` | `asyncio.create_task(...)` | Background polling coroutine, same loop |
| SQLAlchemy | `create_async_engine` + `AsyncSession` | All DB access is async via asyncpg |

---

## Transaction Boundaries

The session lifecycle has two distinct patterns:

**Pattern A — FastAPI Dependency-Injected Session (webhook path):**
- `get_session()` in `src/database.py:30` provides one `AsyncSession` per request via `Depends(get_session)`
- The router and each dependency each open explicit `session.begin()` sub-transactions
- This creates multiple `begin()` calls on the same session object across chained dependencies — session reuse across dependency chain (`src/sms/dependencies.py:75, 91, 105`, `src/sms/router.py:46`)
- Final commit is in the router (`session.begin()` block at line 46)

**Pattern B — Temporal Activity Sessions:**
- `get_sessionmaker()()` is called directly (not via FastAPI DI) to open fresh sessions
- `process_message_activity` opens one session for the full pipeline run (`src/temporal/activities.py:54`)
- Session is passed via `PipelineContext` to handlers; handlers call `session.commit()` themselves
- `sync_pinecone_queue_activity` opens a new session per row update (`src/temporal/activities.py:130, 147`) — creates N sessions for N rows
- `JobPostingHandler` opens a second session `s2` on Pinecone failure for queue insert (`src/pipeline/handlers/job_posting.py:94`)

Transaction ownership is caller-defined by convention (documented in `BaseRepository._persist` docstring) but not enforced by the type system.

---

## Error Handling

**Strategy:** Exception-per-gate with FastAPI exception handlers for the HTTP path; Temporal retry policies for the async path.

**Patterns:**
- `EarlyReturn` base exception + subclasses (`DuplicateMessageSid`, `RateLimitExceeded`) signal HTTP 200 + empty TwiML to Twilio — prevents retry storms (`src/sms/exceptions.py`)
- `TwilioSignatureInvalid` maps to 403 response (`src/exceptions.py`)
- Temporal `ApplicationError(non_retryable=True)` used when message row not found after webhook write — prevents futile retries (`src/temporal/activities.py:62`)
- `tenacity` retry with exponential backoff on GPT `RateLimitError` / `APIStatusError` (`src/extraction/service.py:80`)
- Pinecone upsert failure in `JobPostingHandler`: caught, logged, enqueued to `pinecone_sync_queue` fallback — error is never re-raised, so pipeline always commits even on Pinecone failure

---

## Cross-Cutting Concerns

**Logging:** structlog with JSON renderer + OTel trace/span ID injection (`src/main.py:56`). Structured fields: `message_sid`, `phone_hash`, `job_id`, `error`.

**Observability:** OpenTelemetry with OTLP gRPC exporter to Jaeger. `FastAPIInstrumentor` auto-instruments HTTP; `SQLAlchemyInstrumentor` auto-instruments DB; Temporal `TracingInterceptor` propagates context into workflows/activities. Manual `tracer.start_as_current_span()` in orchestrator, handlers, and activities.

**Metrics:** Prometheus via `prometheus-fastapi-instrumentator`. Custom metrics in `src/metrics.py`: GPT call counters/histograms, Pinecone queue depth gauge, pipeline failure counter.

**Validation:** Pydantic `BaseModel` for all API input/output schemas and `BaseSettings` for config. `model_validator(mode="after")` enforces required credentials at startup.

**Authentication:** Twilio HMAC signature validation in `validate_twilio_request` dependency; bypassed when `settings.env == "development"` (`src/sms/dependencies.py:57`).

**Money:** Dollar-to-cent conversion at extraction boundary (`src/money.py`); cent-to-dollar only at SMS reply boundary (`src/matches/formatter.py`). All DB columns and internal arithmetic are integer cents.

**DI Graph:** Constructed manually in `lifespan()` in `src/main.py:122`; stored on `app.state`. No DI framework — explicit constructor injection for services and repositories.

---

## Architectural Smells

**1. MatchService is orphaned dead code:**
`MatchService` (`src/matches/service.py`), `MatchRepository` (`src/matches/repository.py`), and `format_match_sms` (`src/matches/formatter.py`) are fully implemented but never invoked in any workflow, activity, or route. `WorkerGoalHandler` persists a `WorkGoal` record and commits but never calls `MatchService.match()`. The entire matches domain is unreachable from the live pipeline.

**2. Module-level mutable singletons in activities (`src/temporal/activities.py:24-25`):**
`_orchestrator` and `_openai_client` are `None`-initialized module globals mutated by `run_worker()` before worker start (`src/temporal/worker.py:30-31`). If activities are unit-tested without calling `run_worker()`, they will fail on `None._orchestrator`. Both are annotated `| None` but the `None` path is never handled in the activity bodies.

**3. `JobCreate.user_id` silently dropped (`src/jobs/schemas.py`, `src/pipeline/handlers/job_posting.py:46`):**
`JobPostingHandler` passes `user_id=ctx.user_id` to `JobCreate(...)` but `JobCreate` does not declare a `user_id` field. Pydantic `BaseModel` without `model_config(extra='forbid')` silently ignores unknown fields. The `Job` model also has no `user_id` column — ownership is traced via `job.message_id → message.user_id`. This is intentional by 3NF design but the handler silently passes an extra kwarg, which is misleading and could mask future field omissions.

**4. `WorkGoalCreate.raw_sms` and `JobCreate.raw_sms` never persisted:**
Both create-schemas declare `raw_sms: str` (`src/work_goals/schemas.py:8`, `src/jobs/schemas.py:19`) and handlers pass it. However, `WorkGoalRepository.create` (`src/work_goals/repository.py:14`) constructs `WorkGoal(...)` without mapping `raw_sms`, and the `WorkGoal` model has no such column. `JobRepository.create` has the same issue. The field is validated and passed but silently dropped.

**5. `sync_pinecone_queue_activity` opens N DB sessions for N rows (`src/temporal/activities.py:130, 147`):**
For a batch of 50 rows, this opens up to 100 DB connections (two per row: success update + failure update). A single bulk UPDATE within the activity's already-open session would be correct and efficient.

**6. Chained dependency session reuse with multiple nested `begin()` calls (`src/sms/dependencies.py`):**
`validate_twilio_request`, `check_idempotency`, `get_or_create_user`, and `enforce_rate_limit` each call `Depends(get_session)`. FastAPI caches the session per request, so they share one `AsyncSession` — but each opens its own `session.begin()` nested transaction. If any sub-transaction rolls back, the shared session state could become inconsistent. The pattern is functional but fragile and non-obvious.

**7. Inline raw SQL for `UPDATE message SET message_type` duplicated across three handlers:**
`src/pipeline/handlers/job_posting.py:65`, `src/pipeline/handlers/worker_goal.py:47`, `src/pipeline/handlers/unknown.py:33` all execute the same raw `sa_text("UPDATE message SET message_type = '...' WHERE id = :mid")` rather than using ORM attribute assignment or a shared repository method.

---

*Architecture analysis: 2026-04-22*
