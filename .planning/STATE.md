---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: executing
stopped_at: Completed 02.12-01-PLAN.md
last_updated: "2026-04-03T06:51:40.102Z"
last_activity: 2026-04-03
progress:
  total_phases: 18
  completed_phases: 15
  total_plans: 29
  completed_plans: 29
  percent: 82
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-08)

**Core value:** A worker who texts their earnings goal must receive a ranked list of jobs that lets them hit that goal in the shortest possible time.
**Current focus:** Phase 02.13 — ruthlessly-refactor-this-codebase-where-appropriate-in-light-of-the-latest-revisions-to-agents-md

## Current Position

Phase: 03
Plan: Not started
Status: Executing Phase 02.13
Last activity: 2026-04-03 - Completed quick task 260403-4ps: per-service env file restructure for docker-compose

Progress: [████████░░] 82% (13 of 15 phases complete, all 27 plans complete)

## What's Built

The app is production-ready from the infrastructure and domain-logic perspective. Everything through extraction and storage is implemented, tested, and hardened:

### Complete

- ✅ Async FastAPI skeleton, 5-gate Twilio webhook security chain
- ✅ 3NF schema (User / Message / Job / WorkRequest / RateLimit / AuditLog / PineconeSyncQueue)
- ✅ gpt-5.3-chat-latest classify+extract via `beta.chat.completions.parse` (discriminated union)
- ✅ PipelineOrchestrator: full pipeline (GPT → storage → Pinecone), single commit per branch
- ✅ Pinecone embedding write with `text-embedding-3-small`; failed writes queued + retried via Temporal cron
- ✅ Full observability: structlog JSON, OTel → Jaeger v2 (OpenSearch), Prometheus → Grafana, TracingInterceptor on Temporal
- ✅ Temporal: ProcessMessageWorkflow (4 attempts, on_failure activity), SyncPineconeQueueWorkflow (cron sweep)
- ✅ Pipeline handler pattern (Chain of Responsibility): JobPostingHandler, WorkerGoalHandler, UnknownMessageHandler
- ✅ Multi-stage Dockerfile (non-root, HEALTHCHECK), render.yaml Blueprint, GitHub Actions CI
- ✅ Edge-case hardening: config validation, GPT None guard, rate limit rolling window, graceful shutdown

### Not Started

- ⏳ Phase 3: MatchService (earnings math SQL, ranked SMS formatter, empty-match fallback)
- ⏳ Phase 4: Outbound SMS for job posters and workers, STOP/START pass-through, Render.com deploy

## Architecture Snapshot

```
src/
├── main.py                    # FastAPI app + lifespan DI graph
├── config.py                  # Nested Pydantic Settings (4 sub-models)
├── database.py                # Async SQLAlchemy engine + sessionmaker
├── models.py                  # Central SQLModel aggregator
├── repository.py              # Base repository class
├── metrics.py                 # Prometheus metric singletons
├── exceptions.py              # Custom exceptions
├── sms/                       # Webhook route, MessageRepository, AuditLogRepository
├── extraction/                # ExtractionService (GPT-only), schemas, Pinecone client
├── pipeline/                  # PipelineOrchestrator + handler registry
│   ├── orchestrator.py        #   Classify → audit → dispatch
│   ├── context.py             #   PipelineContext dataclass
│   └── handlers/              #   base.py, job_posting.py, worker_goal.py, unknown.py
├── temporal/                  # Workflow orchestration
│   ├── workflows.py           #   ProcessMessageWorkflow, SyncPineconeQueueWorkflow
│   ├── activities.py          #   Activity implementations
│   └── worker.py              #   Client (TracingInterceptor), worker, cron scheduling
├── jobs/                      # JobRepository, Job SQLModel
├── work_requests/             # WorkRequestRepository, WorkRequest SQLModel
├── users/                     # UserRepository, User SQLModel
└── matches/                   # Match SQLModel (placeholder, Phase 3)
```

**DI Graph (lifespan):**

```
AsyncOpenAI → wrap_openai (Braintrust) → ExtractionService
Repos (JobRepository, WorkRequestRepository, AuditLogRepository) → instantiated
Handlers [JobPostingHandler, WorkerGoalHandler, UnknownMessageHandler] → built with repos
ExtractionService + AuditLogRepository + handlers → PipelineOrchestrator
PipelineOrchestrator → app.state (accessed by Temporal activities)
Temporal client (TracingInterceptor) → worker task in lifespan
```

**Docker Compose (local dev, 9 services):**
postgres | opensearch | jaeger-collector | jaeger-query | app | temporal | temporal-ui | prometheus | grafana

**Deployment (production):**
Render.com — render.yaml Blueprint (web service + PostgreSQL 16 basic-256mb)

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Phase 01-01]: postgres:16 plain image (not pgvector) — Pinecone is the vector store
- [Phase 01-01]: Async Alembic env.py using asyncio.run() — required for asyncpg driver
- [Phase 01-01]: expire_on_commit=False on async_sessionmaker — async SQLAlchemy cannot lazy-load after commit
- [Phase 01-01]: SQLite+aiosqlite for test DB — no postgres dependency in unit tests
- [Phase 01-02]: validate_twilio_request raises HTTPException(403) directly — simpler for dependency pattern
- [Phase 01-02]: register_phone raw SQL includes created_at explicitly — SQLModel default_factory does not fire for raw SQL inserts
- [Phase 01-03]: inngest_client uses is_production=not settings.inngest_dev — INNGEST_DEV=1 in .env enables dev mode without signing key
- [Phase 01-03]: autouse _auto_mock_inngest_send fixture in conftest prevents real Inngest HTTP calls from corrupting async event loop in all tests
- [Phase 01.1]: User/Message/WorkRequest replace Phone/InboundMessage/Worker with integer FKs — eliminates phone_hash string pseudo-FKs
- [Phase 01.1]: ON CONFLICT (user_id, created_at) column list syntax used for SQLite/PG compatibility in rate_limit upsert
- [Phase 02-gpt-extraction-service]: patch target is src.extraction.service.wrap_openai (not braintrust.wrap_openai) — service.py uses a direct import
- [Phase 02-gpt-extraction-service]: ExtractionService.process() keeps minimal signature (sms_text, phone_hash) — message_id and db_session added in Plan 02-02 when storage is wired
- [Phase 02-gpt-extraction-service]: WorkRequestRepository (not WorkerRepository) — 3NF schema uses work_request table
- [Phase 02-gpt-extraction-service]: ExtractionService.process() backward-compatible with session=None for existing tests
- [Phase 02-gpt-extraction-service]: PineconeSyncQueue SQLModel in src/extraction/models.py registered via src/models.py
- [Phase 02-gpt-extraction-service]: Call process_message._handler(ctx) in tests — Inngest Function wrapper is not directly callable
- [Phase 02-gpt-extraction-service]: Twilio send in unknown branch uses asyncio.to_thread() — Twilio REST client is synchronous
- [Phase 02.1-01]: Nested Settings use model_validator(mode=after) remapping flat env vars — no .env changes required
- [Phase 02.1-01]: Rate limit SELECT uses raw SQL to bypass ORM identity cache stale reads across multiple calls in same session
- [Phase 02.1-01]: sms/service.py is now a pure-function module — hash_phone and emit_message_received_event only
- [Phase 02.1-02]: ExtractionService receives pre-built openai_client — caller wraps with braintrust.wrap_openai before injection
- [Phase 02.1-02]: PipelineOrchestrator.run() issues single session.commit() per branch; Pinecone fires after commit to avoid rollback coupling
- [Phase 02.1-02]: Pinecone failure enqueued in separate session so main transaction is not affected
- [Phase 02.1-03]: _orchestrator module-level var in inngest_client.py set by lifespan — cleanest circular import avoidance pattern
- [Phase 02.1-03]: Twilio unknown reply moved from inngest_client.py to PipelineOrchestrator.run() unknown branch — orchestrator owns all pipeline logic
- [Phase 02.3]: ALWAYS_ON sampler (not ParentBasedTraceIdRatio) — unambiguous, no parent-based override
- [Phase 02.3]: opensearch replicas=0 for single-node local dev — replicas>0 causes yellow cluster health
- [Phase 02.3]: GIT_SHA env var maps to git_sha flat field in Settings, wired to observability.service_version
- [Phase 02.3]: Module-level tracer patched directly in test fixtures — provider override warning makes InMemorySpanExporter approach unreliable
- [Phase 02.3]: Twilio span created in async context wrapping asyncio.to_thread — OTel context not propagated into threads
- [Phase 02.3]: jaeger_query removed from collector extensions list — not a valid extension for standalone collector, caused startup failure
- [Phase 02.4-01]: Metrics imported inside process() (not at module top of service.py) to avoid circular imports
- [Phase 02.4-01]: _call_with_retry returns (result, usage) tuple — process() unpacks and records token metrics
- [Phase 02.4-02]: Dashboard datasource referenced by uid='prometheus' to ensure reliable resolution after provisioning
- [Phase 02.4-02]: grafana_data is the first named Docker volume in this project; others use bind mounts
- [Phase 02.5]: Lazy import of pipeline_failures_total inside _handle_process_message_failure — consistent with Phase 02.4 circular import avoidance pattern
- [Phase 02.5]: HEALTHCHECK probes /health (liveness) not /readyz — health probe must not depend on DB connectivity
- [Phase 02.5]: render.yaml GIT_SHA uses empty string default; operators set manually or via deploy hooks
- [Phase 02.5]: CI uses SQLite+aiosqlite for test isolation in GitHub Actions
- [Phase 02.5]: _openai_client module-level var in inngest_client.py set by lifespan — same pattern as _orchestrator, avoids circular imports
- [Phase 02.5]: Counter increment tests use _value.get() internal before/after comparison — avoids registry scrape
- [Phase 02.6-01]: STACK.md and ARCHITECTURE.md now reflect the actual built system (Phases 01–02.5) with 0 pgvector references, 2026-03-08 date, HIGH confidence sourced from STATE.md/PROJECT.md/REQUIREMENTS.md
- [Phase 02.6]: FEATURES.md and PITFALLS.md patched with accurate ✅/⏳ status, Phase 3/4 forward-looking content, 8 new implementation pitfalls, zero pgvector references
- [Phase 02.7-01]: README links to .env.example via explicit cp command; migrations step marked optional when using Docker
- [Phase 02.9]: Replaced Inngest with Temporal: activities + workflows + worker in src/temporal/, RPCError for cron idempotency
- [Phase 02.10]: Wire TracingInterceptor on Client.connect only — worker inherits interceptors from client automatically
- [Phase 02.11]: Settings._validate_required_credentials fires before _build_sub_models since both are mode=after validators executed in declaration order
- [Phase 02.11]: Rate limit uses Python datetime.now(UTC) bound param instead of NOW() SQL function for SQLite test compatibility

### Roadmap Evolution

- Phase 1.1 inserted after Phase 1: Apply revised 3NF schema (URGENT)
- Phase 2.1 inserted after Phase 2: Refactor persistence layer and service boundaries (INSERTED)
- Phase 02.3 inserted after Phase 2: Migrate Jaeger to v2 (URGENT)
- Phase 02.4 inserted after Phase 2: Ensure Prometheus is setup (URGENT)
- Phase 02.2 removed: consolidated into Phase 02.4
- Phase 02.5 inserted after Phase 02.4: Production hardening to staff engineer standards (INSERTED)
- Phase 02.6 inserted after Phase 2: Ensure research docs are current (URGENT)
- Phase 02.7 inserted after Phase 2: flesh out the README.md to also include instructions for getting setup locally (URGENT)
- Phase 02.10 inserted after Phase 2: be sure the temporal flows leverage distributed tracing via jaeger (INSERTED)
- Phase 02.12 inserted after Phase 2: simplify architecture — distill app essence and map domains canonically (INSERTED)
- Phase 02.13 inserted after Phase 2: ruthlessly refactor this codebase where appropriate in light of the latest revisions to AGENTS.md (URGENT)

### Pending Todos

None.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 1 | ensure all env variables, or values associated with those use a reference in the .env file, and ripple out the relevant changes throughout the codebase where appropriate | 2026-03-08 | 3c04ff2 | [1-ensure-all-env-variables-or-values-assoc](./quick/1-ensure-all-env-variables-or-values-assoc/) |
| 2 | make sure any strings with url's that could change across envs i.e. production v staging v dev, are extraced out into the .env file, and in turn have string interpolation used elsewhere | 2026-03-08 | 6f9e3d6 | [2-make-sure-any-strings-with-url-s-that-co](./quick/2-make-sure-any-strings-with-url-s-that-co/) |
| 260403-30x | update all docs | 2026-04-03 | c69eb3d | [260403-30x-update-all-docs](./quick/260403-30x-update-all-docs/) |
| 260403-48b | ensure all magic numbers are constantized. Ensure any values that would vary between environments, for all code across the repo, are in env files mapped to the current, and expected environments (specifically development, staging, production) use the following naming conventions: .env.development, .env.staging, and .env.production. Be sure all values that are stored as an env var are parameterized throughout the codebase to allow for substitution depending on the env file loaded | 2026-04-03 | 1e37f0c | [260403-48b-ensure-all-magic-numbers-are-constantize](./quick/260403-48b-ensure-all-magic-numbers-are-constantize/) |
| 260403-4ps | be sure all environment variable key values are pulled from env variables with interpolation used, and values from other env vars reused if possible. Load env variables exclusively from .env files in the docker-compose file, with a separate env file per env for each service that uses env vars | 2026-04-03 | 8fac221 | [260403-4ps-be-sure-all-environment-variable-key-val](./quick/260403-4ps-be-sure-all-environment-variable-key-val/) |

### Blockers/Concerns

- [Phase 3]: gpt-5.3-chat-latest model string should be verified against OpenAI model catalog before Phase 3 planning (can run `/gsd:research-phase 3` to confirm)
- [Phase 4]: Render.com production deploy has not been executed yet — first deploy validation is part of Phase 4

## Session Continuity

Last session: 2026-04-03T05:44:33.655Z
Stopped at: Completed 02.12-01-PLAN.md
Resume file: None
Next action: `/gsd:plan-phase 3` or `/gsd:execute-phase 3`
