# Architecture

**Analysis Date:** 2026-04-06

## Pattern Overview

**Overall:** Event-driven pipeline with Temporal workflow orchestration

**Key Characteristics:**
- SMS-first labor marketplace: inbound Twilio SMS is the sole entry point for all user interaction
- GPT-powered extraction classifies messages into domain actions (job postings, work goals, unknown)
- Temporal durable workflows handle all async processing with retry semantics
- Chain of Responsibility pattern dispatches classified messages to domain-specific handlers
- Constructor-based dependency injection wired in the FastAPI lifespan
- Repository pattern with flush-only persistence (caller owns the transaction)
- All monetary values stored as integer cents; conversion at system boundaries only

## Layers

**HTTP / Webhook Layer:**
- Purpose: Receive inbound Twilio SMS webhooks, run pre-flight validation gates, persist raw message, emit Temporal workflow
- Location: `src/sms/router.py`, `src/sms/dependencies.py`
- Contains: Single POST endpoint `POST /webhook/sms`, dependency chain for validation/idempotency/rate-limiting
- Depends on: `src/sms/service.py`, `src/sms/repository.py`, `src/users/repository.py`, `src/temporal/`
- Used by: Twilio (external)

**Temporal Workflow Layer:**
- Purpose: Durable execution of message processing with automatic retries and failure handling
- Location: `src/temporal/workflows.py`, `src/temporal/activities.py`, `src/temporal/worker.py`
- Contains: `ProcessMessageWorkflow` (per-message), `SyncPineconeQueueWorkflow` (cron)
- Depends on: `src/pipeline/orchestrator.py`, `src/extraction/`, `src/database.py`
- Used by: SMS webhook (starts workflows), Temporal scheduler (cron)

**Pipeline Layer:**
- Purpose: Classify SMS via GPT, then dispatch to the correct domain handler
- Location: `src/pipeline/orchestrator.py`, `src/pipeline/context.py`, `src/pipeline/handlers/`
- Contains: `PipelineOrchestrator`, `PipelineContext` dataclass, `MessageHandler` ABC, concrete handlers
- Depends on: `src/extraction/service.py`, domain handlers, `src/sms/audit_repository.py`
- Used by: `src/temporal/activities.py` (`process_message_activity`)

**Extraction Layer:**
- Purpose: GPT classification and structured data extraction from SMS text
- Location: `src/extraction/service.py`, `src/extraction/schemas.py`, `src/extraction/prompts.py`, `src/extraction/utils.py`
- Contains: `ExtractionService` (GPT calls with retry), Pydantic extraction schemas, Pinecone embedding utility
- Depends on: OpenAI API, Pinecone API, Braintrust (logging)
- Used by: `src/pipeline/orchestrator.py`, `src/pipeline/handlers/job_posting.py`

**Domain Layer (Jobs):**
- Purpose: Persist job postings extracted from SMS, find candidates for matching
- Location: `src/jobs/models.py`, `src/jobs/repository.py`, `src/jobs/schemas.py`
- Contains: `Job` SQLModel, `JobRepository`, `JobCreate` Pydantic schema
- Depends on: `src/repository.py` (BaseRepository)
- Used by: `src/pipeline/handlers/job_posting.py`, `src/matches/service.py`

**Domain Layer (Work Goals):**
- Purpose: Persist worker earnings goals extracted from SMS
- Location: `src/work_goals/models.py`, `src/work_goals/repository.py`, `src/work_goals/schemas.py`
- Contains: `WorkGoal` SQLModel, `WorkGoalRepository`, `WorkGoalCreate` Pydantic schema
- Depends on: `src/repository.py` (BaseRepository)
- Used by: `src/pipeline/handlers/worker_goal.py`, `src/matches/service.py`

**Domain Layer (Matches):**
- Purpose: Match available jobs to work goals using 0/1 knapsack DP algorithm, format SMS replies
- Location: `src/matches/service.py`, `src/matches/repository.py`, `src/matches/schemas.py`, `src/matches/formatter.py`
- Contains: `MatchService` (DP knapsack), `MatchRepository`, `JobCandidate`/`MatchResult` dataclasses, `format_match_sms()`
- Depends on: `src/jobs/repository.py`, `src/users/models.py`, `src/money.py`
- Used by: Not yet wired into pipeline handlers (future integration)

**Domain Layer (Users):**
- Purpose: User identity via phone hash; upsert-on-first-contact pattern
- Location: `src/users/models.py`, `src/users/repository.py`
- Contains: `User` SQLModel, `UserRepository` with static `get_or_create`
- Depends on: Database
- Used by: `src/sms/dependencies.py` (Gate 3)

**Infrastructure Layer:**
- Purpose: Pulumi IaC for GKE deployment
- Location: `infra/__main__.py`, `infra/components/`
- Contains: Cluster, database, secrets, cert-manager, ingress, Temporal, observability stack components
- Depends on: GCP (GKE, Cloud SQL, GCR), Pulumi
- Used by: CI/CD deployment

## Data Flow

**Inbound SMS Processing (primary flow):**

1. Twilio POST `/webhook/sms` hits `src/sms/router.py`
2. FastAPI dependency chain in `src/sms/dependencies.py` runs four gates sequentially:
   - Gate 1: `validate_twilio_request` -- signature verification (skipped in development)
   - Gate 2: `check_idempotency` -- reject duplicate `MessageSid` via `MessageRepository.check_idempotency()`
   - Gate 3: `get_or_create_user` -- upsert user by `phone_hash` via `UserRepository.get_or_create()`
   - Gate 4: `enforce_rate_limit` -- rolling-window rate limiter via `MessageRepository.enforce_rate_limit()`
3. Route body persists `Message` row and `AuditLog` entry within a single transaction
4. `sms_service.emit_message_received_event()` starts `ProcessMessageWorkflow` in Temporal (fire-and-forget)
5. HTTP 200 with empty TwiML returned immediately
6. Temporal executes `process_message_activity`:
   a. Resolves `message_id`/`user_id` from DB by looking up the `Message` row
   b. Calls `PipelineOrchestrator.run()`
   c. Orchestrator calls `ExtractionService.process()` -- GPT classifies + extracts structured data
   d. Orchestrator iterates handler chain (Chain of Responsibility):
      - `JobPostingHandler.can_handle()` -- true if `message_type == "job_posting"`
      - `WorkerGoalHandler.can_handle()` -- true if `message_type == "work_goal"`
      - `UnknownMessageHandler.can_handle()` -- always true (catch-all, must be last)
   e. Matching handler persists domain entity, updates `message.message_type`, writes audit log, commits
7. On permanent failure after retries: `handle_process_message_failure_activity` logs and increments `pipeline_failures_total` Prometheus counter

**Pinecone Sync (background cron):**

1. `SyncPineconeQueueWorkflow` runs on cron schedule (default: every 5 minutes)
2. `sync_pinecone_queue_activity` queries `pinecone_sync_queue` for up to 50 pending rows
3. For each row: generates embedding via OpenAI (`text-embedding-3-small`), upserts to Pinecone index
4. Updates row status to `success` or `failed` with retry count increment

**Job Matching (implemented but not yet wired into pipeline):**

1. `MatchService.match()` receives a `WorkGoal`
2. `JobRepository.find_candidates_for_goal()` fetches available jobs with computable earnings (excludes `pay_type == "unknown"`, null pay rates, hourly jobs without duration)
3. `_build_candidates()` computes earnings per job (cents), loads poster phone via message->user join (batched to avoid N+1)
4. `_dp_select()` runs 0/1 knapsack DP to maximize total earnings toward target, with secondary objective of minimizing total duration
5. `_sort_results()` sorts by soonest `ideal_datetime` first, then shortest duration; NULL datetimes sort last
6. `MatchRepository.persist_matches()` saves `(job_id, work_goal_id)` pairs, skipping duplicates via IntegrityError catch
7. `format_match_sms()` builds SMS reply text (max 5 jobs, partial-match summary)

**State Management:**
- PostgreSQL is the single source of truth for all domain state
- Pinecone is a derived index (job embeddings) with eventual consistency via `pinecone_sync_queue`
- Temporal provides durable workflow state and retry semantics
- No in-memory caching beyond `lru_cache` on `get_settings()` and `get_engine()`

## DI Graph (Lifespan Wiring)

Constructed in `src/main.py` `lifespan()`:

```
AsyncOpenAI (wrapped by Braintrust) -> ExtractionService
TwilioClient -> UnknownMessageHandler

ExtractionService + AuditLogRepository -> PipelineOrchestrator
  handlers list (ordered):
    1. JobPostingHandler(JobRepository, AuditLogRepository, write_job_embedding, ExtractionService)
    2. WorkerGoalHandler(WorkGoalRepository, AuditLogRepository)
    3. UnknownMessageHandler(TwilioClient, ExtractionService)

PipelineOrchestrator -> app.state.orchestrator
Temporal Client (with TracingInterceptor) -> app.state.temporal_client
Temporal Worker task -> asyncio.create_task(run_worker(...))
```

Temporal activities access the orchestrator and OpenAI client via module-level singletons set in `src/temporal/activities.py` (`_orchestrator`, `_openai_client`), initialized by `run_worker()` before worker starts.

## Key Abstractions

**BaseRepository:**
- Purpose: Template Method for flush-only persistence; caller owns the transaction
- Location: `src/repository.py`
- Pattern: All domain repositories extend this, call `self._persist(session, entity)` which does `session.add()` + `session.flush()`

**MessageHandler (Chain of Responsibility):**
- Purpose: Polymorphic dispatch of classified messages to domain logic
- Location: `src/pipeline/handlers/base.py`
- Implementations: `src/pipeline/handlers/job_posting.py`, `src/pipeline/handlers/worker_goal.py`, `src/pipeline/handlers/unknown.py`
- Pattern: `can_handle(result) -> bool` + `handle(ctx) -> None`; first match wins; ordering matters (unknown must be last)

**PipelineContext:**
- Purpose: Immutable value bag passed through the handler chain
- Location: `src/pipeline/context.py`
- Pattern: Dataclass carrying `session`, `result`, `sms_text`, `phone_hash`, `message_id`, `user_id`, `message_sid`, `from_number`

**ExtractionResult:**
- Purpose: Typed GPT output -- classification + extracted structured data
- Location: `src/extraction/schemas.py`
- Pattern: Pydantic model with `message_type` Literal discriminator and optional sub-models (`JobExtraction`, `WorkerExtraction`, `UnknownMessage`)

**EarlyReturn Exception Hierarchy:**
- Purpose: Short-circuit webhook processing with HTTP 200 (Twilio retries on 4xx)
- Location: `src/sms/exceptions.py`
- Pattern: `EarlyReturn` base, `DuplicateMessageSid` and `RateLimitExceeded` subclasses; caught by FastAPI exception handler returning empty TwiML

## Entry Points

**FastAPI Application:**
- Location: `src/main.py` -- `create_app()` factory, `app` module-level singleton
- Triggers: `uvicorn src.main:app`
- Responsibilities: Wire DI graph in lifespan, configure OTel/structlog, start Temporal worker, register routes and exception handlers

**Temporal Worker (in-process):**
- Location: `src/temporal/worker.py` -- `run_worker()` coroutine
- Triggers: Started as `asyncio.create_task` in FastAPI lifespan
- Responsibilities: Execute `ProcessMessageWorkflow` and `SyncPineconeQueueWorkflow` activities

**Webhook Endpoint:**
- Location: `src/sms/router.py` -- `POST /webhook/sms`
- Triggers: Twilio HTTP callback on inbound SMS
- Responsibilities: Validate, persist raw message, emit Temporal workflow, return TwiML

**Health Endpoints:**
- Location: `src/main.py` -- `GET /health` (liveness), `GET /readyz` (readiness with DB connectivity check)
- Triggers: Kubernetes probes, load balancer health checks

## Error Handling

**Strategy:** Fail-fast at boundaries, retry in workflows, graceful degradation for non-critical paths

**Patterns:**
- Webhook dependency gates raise `EarlyReturn` subclasses -> exception handler returns HTTP 200 empty TwiML (Twilio never sees 4xx, preventing retries)
- `TwilioSignatureInvalid` returns HTTP 403 via dedicated handler in `src/exceptions.py`
- GPT calls use `tenacity` retry with random exponential backoff for `RateLimitError`/`APIStatusError` (up to 4 attempts, 1-60s wait) in `src/extraction/service.py`
- Temporal `ProcessMessageWorkflow` retries up to 4 attempts with exponential backoff (1s initial, 2x coefficient, 5min max); on permanent failure, `handle_process_message_failure_activity` logs + increments `pipeline_failures_total` Prometheus counter
- Pinecone writes fail gracefully: on error, job is enqueued to `pinecone_sync_queue` for retry by cron workflow
- Unparseable GPT response raises `ApplicationError(non_retryable=False)` to allow Temporal retry
- Settings validation in `src/config.py` raises `ValueError` at startup if required credentials are missing

## Cross-Cutting Concerns

**Logging:**
- structlog with JSON rendering and OTel trace/span ID injection (`src/main.py` -- `_add_otel_context` processor)
- All domain modules use `structlog.get_logger()` for structured contextual logging
- Braintrust logger for GPT call observability (`src/extraction/service.py`)

**Tracing:**
- OpenTelemetry with OTLP/gRPC exporter to Jaeger (`src/main.py` -- `_configure_otel`)
- Auto-instrumentation: FastAPI routes (`FastAPIInstrumentor`), SQLAlchemy queries (`SQLAlchemyInstrumentor`)
- Manual spans: pipeline orchestration, GPT calls, Pinecone upserts, Twilio sends, Temporal activities
- Temporal `TracingInterceptor` propagates trace context across workflow/activity boundaries (`src/temporal/worker.py`)
- Semantic convention attributes defined in `src/pipeline/constants.py` (messaging.*, db.*, app.*)

**Metrics:**
- Prometheus via `prometheus-fastapi-instrumentator` (automatic HTTP metrics) + custom metrics in `src/metrics.py`
- Custom metrics: `gpt_calls_total` (by classification_result), `gpt_call_duration_seconds`, `gpt_input_tokens_total`, `gpt_output_tokens_total`, `pinecone_sync_queue_depth`, `pipeline_failures_total` (by function)
- Background gauge updater polls `pinecone_sync_queue` every 15s (`_update_gauges` in `src/main.py`)

**Validation:**
- Pydantic schemas for all domain create operations (`JobCreate`, `WorkGoalCreate`, `TwilioWebhookPayload`)
- Database-level CHECK constraints on `job` (positive pay_rate, valid status) and `work_goal` (positive target_earnings)
- FastAPI dependency chain for request-level validation (signature, idempotency, rate limit)

**Authentication:**
- Twilio webhook signature validation via `twilio.request_validator.RequestValidator` (bypassed when `env == "development"`)
- No user authentication beyond phone identity (SHA-256 hash of E.164 number)

**Money:**
- All monetary values stored as integer cents in the database
- `dollars_to_cents()` called at persistence boundary (after GPT extraction)
- `cents_to_dollars()` called at SMS reply boundary (formatting)
- Utility module: `src/money.py`

## Database Schema (3NF)

**Tables:**
- `user` -- identity by `phone_hash` (unique), optional `phone_e164`
- `message` -- inbound SMS; FK to `user`; `message_type` updated after classification
- `job` -- extracted job posting; FK to `message` (unique); `pay_rate` in cents; `status` enum
- `work_goal` -- extracted earnings goal; FK to `message` (unique); `target_earnings` in cents
- `match` -- join table `(job_id, work_goal_id)` with UNIQUE constraint
- `rate_limit` -- rolling-window rate limit rows; FK to `user`
- `audit_log` -- append-only event log; FK to `message` (optional)
- `pinecone_sync_queue` -- retry queue for failed Pinecone upserts; FK to `job`

**Migrations:** Alembic in `migrations/versions/`, 6 migration files from `2026-03-05` to `2026-04-04`

---

*Architecture analysis: 2026-04-06*
