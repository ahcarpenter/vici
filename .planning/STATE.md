---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: planning
stopped_at: Completed 02.6-01-PLAN.md
last_updated: "2026-03-08T15:09:32.527Z"
last_activity: "2026-03-08 - Completed quick task 2: make sure any strings with url's that could change across envs i.e. production v staging v dev, are extraced out into the .env file, and in turn have string interpolation used elsewhere"
progress:
  total_phases: 10
  completed_phases: 6
  total_plans: 20
  completed_plans: 19
  percent: 78
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-08)

**Core value:** A worker who texts their earnings goal must receive a ranked list of jobs that lets them hit that goal in the shortest possible time.
**Current focus:** Phase 3 — Earnings Math Matching (next to execute)

## Current Position

Phase: Phase 3 — Earnings Math Matching (not yet started)
Status: Ready to plan/execute Phase 3
Last activity: 2026-03-08 - Completed quick task 2: make sure any strings with url's that could change across envs i.e. production v staging v dev, are extraced out into the .env file, and in turn have string interpolation used elsewhere

Progress: [████████░░] 78% (7 of 9 phases complete, all 19 plans complete)

## What's Built

The app is production-ready from the infrastructure and domain-logic perspective. Everything through extraction and storage is implemented, tested, and hardened:

### Complete
- ✅ Async FastAPI skeleton, 5-gate Twilio webhook security chain
- ✅ 3NF schema (User / Message / Job / WorkRequest / RateLimit / AuditLog / PineconeSyncQueue)
- ✅ gpt-5.3-chat-latest classify+extract via `beta.chat.completions.parse` (discriminated union)
- ✅ PipelineOrchestrator: full pipeline (GPT → storage → Pinecone), single commit per branch
- ✅ Pinecone embedding write with `text-embedding-3-small`; failed writes queued + retried via Inngest cron
- ✅ Full observability: structlog JSON, OTel → Jaeger v2 (OpenSearch), Prometheus → Grafana
- ✅ Inngest: `process-message` (3 retries, on_failure handler), `sync-pinecone-queue` (cron sweep)
- ✅ Multi-stage Dockerfile (non-root, HEALTHCHECK), render.yaml Blueprint, GitHub Actions CI
- ✅ Unknown-message graceful SMS reply implemented in PipelineOrchestrator

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
├── inngest_client.py          # process-message + sync-pinecone-queue Inngest functions
├── metrics.py                 # Prometheus metric singletons
├── exceptions.py              # Custom exceptions
├── sms/                       # Webhook route, MessageRepository, AuditLogRepository
├── extraction/                # ExtractionService (GPT-only), PipelineOrchestrator, schemas, Pinecone client
├── jobs/                      # JobRepository, Job SQLModel
├── work_requests/             # WorkRequestRepository, WorkRequest SQLModel
├── users/                     # User SQLModel
└── matches/                   # Match SQLModel (placeholder, Phase 3)
```

**DI Graph (lifespan):**
```
AsyncOpenAI → wrap_openai (Braintrust) → ExtractionService
ExtractionService + repos + pinecone_client + TwilioClient → PipelineOrchestrator
PipelineOrchestrator → inngest_client._orchestrator (module var)
wrap_openai → inngest_client._openai_client (module var)
```

**Docker Compose (local dev, 8 services):**
postgres | opensearch | jaeger-collector | jaeger-query | app | inngest | prometheus | grafana

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

### Roadmap Evolution

- Phase 1.1 inserted after Phase 1: Apply revised 3NF schema (URGENT)
- Phase 2.1 inserted after Phase 2: Refactor persistence layer and service boundaries (INSERTED)
- Phase 02.3 inserted after Phase 2: Migrate Jaeger to v2 (URGENT)
- Phase 02.4 inserted after Phase 2: Ensure Prometheus is setup (URGENT)
- Phase 02.2 removed: consolidated into Phase 02.4
- Phase 02.5 inserted after Phase 02.4: Production hardening to staff engineer standards (INSERTED)
- Phase 02.6 inserted after Phase 2: Ensure research docs are current (URGENT)

### Pending Todos

None.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 1 | ensure all env variables, or values associated with those use a reference in the .env file, and ripple out the relevant changes throughout the codebase where appropriate | 2026-03-08 | 3c04ff2 | [1-ensure-all-env-variables-or-values-assoc](./quick/1-ensure-all-env-variables-or-values-assoc/) |
| 2 | make sure any strings with url's that could change across envs i.e. production v staging v dev, are extraced out into the .env file, and in turn have string interpolation used elsewhere | 2026-03-08 | 6f9e3d6 | [2-make-sure-any-strings-with-url-s-that-co](./quick/2-make-sure-any-strings-with-url-s-that-co/) |

### Blockers/Concerns

- [Phase 3]: gpt-5.3-chat-latest model string should be verified against OpenAI model catalog before Phase 3 planning (can run `/gsd:research-phase 3` to confirm)
- [Phase 4]: Render.com production deploy has not been executed yet — first deploy validation is part of Phase 4

## Session Continuity

Last session: 2026-03-08T15:09:28.512Z
Stopped at: Completed 02.6-01-PLAN.md
Resume file: None
Next action: `/gsd:plan-phase 3` or `/gsd:execute-phase 3`
