# Project Research Summary

**Project:** Vici
**Domain:** SMS-based job matching API (gig economy / labor marketplace via Twilio)
**Researched:** 2026-03-08
**Confidence:** HIGH — derived from the actual built system (Phases 01–02.5 complete). Sources: STATE.md, PROJECT.md, REQUIREMENTS.md.

## Executive Summary

Vici is an SMS-first gig labor marketplace that matches workers to jobs based on earnings math rather than search. As of Phase 02.5, the full extraction and storage pipeline is production-ready: a single Twilio webhook endpoint validates requests through a 5-gate security chain, emits an Inngest event, and returns HTTP 200 to Twilio immediately. The Inngest `process-message` function then runs `PipelineOrchestrator.run()` — which calls `ExtractionService` (GPT classify+extract via `beta.chat.completions.parse` with a discriminated union schema), stores results in PostgreSQL, and writes job embeddings to Pinecone. The complete observability stack is in place: structlog JSON, OTel → Jaeger v2 (OpenSearch), Prometheus → Grafana. Production infrastructure is ready: multi-stage Dockerfile, render.yaml Blueprint IaC, GitHub Actions CI.

The key architectural decision is to return HTTP 200 to Twilio immediately after emitting an Inngest `message.received` event — all GPT processing, storage, and Pinecone writes happen inside the `process-message` Inngest function with 3 retries and an `on_failure` handler. This is the implemented pattern. FastAPI BackgroundTasks are NOT used for this purpose — Inngest provides better retry semantics, observability, and failure handling. The data schema is 3NF: `users` (phone_hash), `messages` (MessageSid idempotency), `jobs`, `work_goals`, `rate_limit`, `audit_log`, `matches` (Phase 3 placeholder), `pinecone_sync_queue`. PostgreSQL 16 plain image — no pgvector extension — Pinecone is the external vector store.

Phase 3 (next) adds `MatchService` in `src/matches/` — earnings math SQL (`pay_rate * estimated_duration >= target_earnings`), ranked SMS formatter (3–5 results, 160-char segments), and empty-match fallback reply. Phase 4 wires outbound SMS confirmation to job posters, STOP/START pass-through, and validates the first Render.com production deploy. The remaining gap is verifying the `gpt-5.3-chat-latest` model string against OpenAI's current model catalog before Phase 3 execution.

## Key Findings

### Recommended Stack

The stack is a Python async API stack with five external integrations: Twilio (inbound/outbound SMS), OpenAI (GPT classify+extract + Braintrust LLM observability), Inngest (async event queue), Pinecone (vector store), and PostgreSQL (structured storage). See `.planning/research/STACK.md` for full version matrix.

**Core technologies:**

| Technology | Status | Purpose |
|-----------|--------|---------|
| Python 3.12 + FastAPI | ✅ | HTTP framework + webhook handler — native async, lifespan DI graph |
| SQLAlchemy 2.0 async + asyncpg | ✅ | ORM + async PostgreSQL driver (expire_on_commit=False required) |
| PostgreSQL 16 (plain) | ✅ | Structured storage — 3NF schema, no vector column |
| Alembic | ✅ | Schema migrations (asyncio.run() + conn.run_sync() in env.py) |
| openai SDK (AsyncOpenAI) | ✅ | GPT classify+extract via beta.chat.completions.parse (discriminated union) |
| twilio SDK | ✅ | Signature validation + outbound SMS via asyncio.to_thread() |
| uv | ✅ | Package manager + Dockerfile builder stage |
| Inngest | ✅ | Async event queue — process-message (3 retries) + sync-pinecone-queue cron |
| Braintrust | ✅ | LLM observability — wraps AsyncOpenAI via wrap_openai |
| Pinecone | ✅ | Vector store — text-embedding-3-small (1536 dims), pinecone_sync_queue retry |
| structlog | ✅ | Structured JSON logging (phone hash, message_id, trace_id) |
| OTel + Jaeger v2 (OpenSearch) | ✅ | Distributed tracing — ALWAYS_ON sampler, OTLP gRPC |
| Prometheus + Grafana | ✅ | Metrics + pre-built dashboard, auto-provisioned |
| pydantic-settings | ✅ | Nested Settings — 4 sub-models via model_validator(mode=after) |

**Not adopted (removed from stack):**
- pgvector / pgvector-python — Pinecone replaces this
- FastAPI BackgroundTasks — Inngest replaces this for async processing
- tenacity — Inngest handles retries natively (3 configured)
- sentry-sdk — not in use
- gunicorn — Render.com uses Docker runtime directly
- Redis — rate limiting uses PostgreSQL TTL counters

### Expected Features

The feature set is well-defined with a clear v1/future split. All v1 must-haves through Phase 02.5 are complete; Phase 3 and Phase 4 items remain.

**Must have — implementation status:**
- ✅ Twilio X-Twilio-Signature validation (SEC-01)
- ✅ MessageSid idempotency (SEC-02)
- ✅ Rate limiting per phone number (SEC-03, PostgreSQL TTL counters)
- ✅ Phone number as identity — auto-registration (IDN-01, IDN-02)
- ✅ Single-call GPT classification + extraction (EXT-01, EXT-02, EXT-03)
- ✅ Graceful fallback for unclassifiable messages (EXT-04 — SMS reply via asyncio.to_thread)
- ✅ HTTP 200 within Twilio timeout (ASYNC-01 — Inngest event-driven)
- ✅ Raw message audit trail (SEC-04 — audit_log table)
- ✅ Pinecone embedding write with retry (VEC-01 — pinecone_sync_queue + Inngest cron)
- ⏳ Earnings math matching (MATCH-01 — Phase 3)
- ⏳ Ranked SMS job list to worker (MATCH-02, MATCH-03 — Phase 3)
- ⏳ SMS confirmation to job poster (STR-03 — Phase 4)
- ⏳ STOP/START keyword pass-through (SEC-05 — Phase 4)

**Should have (deferred):**
- Time-of-send context inference — deferred
- Field-level confidence + clarification prompts — deferred
- SMS query commands ("MY JOBS") — deferred

**Defer (v2+):**
- Semantic / Pinecone vector matching — schema/infrastructure ready; feature deferred
- Web dashboard — defer until SMS channel validated

### Architecture Approach

The implemented architecture is a five-layer async system: FastAPI webhook layer (5-gate security chain), Inngest function layer (PipelineOrchestrator), extraction layer (ExtractionService + GPT), storage layer (repositories + PostgreSQL), and vector layer (Pinecone). The DI graph is built in FastAPI lifespan and injected into Inngest functions via module-level vars (`_orchestrator`, `_openai_client`) set during startup. See `.planning/research/ARCHITECTURE.md` for the full system diagram and data flows.

**Major components:**
1. **Webhook route (`POST /webhook/sms`)** — 5-gate security chain (sig validate → idempotency → user get-or-create → rate limit → persist message), Inngest event emit, returns HTTP 200
2. **PipelineOrchestrator** (`src/extraction/pipeline.py`) — orchestrates full pipeline: Job branch (ExtractionService → JobRepository flush → commit → Pinecone), WorkGoal branch (ExtractionService → WorkGoalRepository flush → commit), Unknown branch (asyncio.to_thread Twilio reply)
3. **ExtractionService** (`src/extraction/service.py`) — single GPT call via `beta.chat.completions.parse` returning `JobExtraction | WorkerExtraction | UnknownMessage` discriminated union; Braintrust-wrapped client
4. **MatchService** (`src/matches/`) — ⏳ Phase 3 placeholder; will implement earnings math SQL + ranked SMS formatter
5. **MessageRepository + AuditLogRepository** (`src/sms/repository.py`) — user get-or-create, message persist, dedup, raw audit storage
6. **JobRepository** (`src/jobs/repository.py`) — CRUD + ⏳ Phase 3 earnings math query
7. **WorkGoalRepository** (`src/work_goals/repository.py`) — CRUD for worker goals
8. **inngest_client** (`src/inngest_client.py`) — `process-message` function (3 retries, on_failure handler → pipeline_failures_total) + `sync-pinecone-queue` cron; module-level `_orchestrator` var set by lifespan
9. **Alembic migrations** (`alembic/`) — asyncio.run() + conn.run_sync() pattern; 3NF schema; no pgvector extension

### Critical Pitfalls

See `.planning/research/PITFALLS.md` for full detail including phase-to-pitfall mapping, recovery costs, and verification checklists.

1. **Twilio signature validation broken by reverse proxy URL mismatch** — Set WEBHOOK_BASE_URL env var; enable Uvicorn --proxy-headers. ✅ Addressed.
2. **Webhook timeout from Twilio retries** — Resolved via Inngest event-driven model (ASYNC-01). ✅ Addressed.
3. **GPT hallucinating structured fields** — Pydantic discriminated union via beta.chat.completions.parse. Active concern for Phase 3 null handling.
4. **Synchronous SQLAlchemy in async FastAPI handlers** — asyncpg + AsyncSession + expire_on_commit=False from Phase 01-01. ✅ Addressed.
5. **Missing raw message audit trail** — audit_log table + AuditLogRepository. ✅ Addressed (SEC-04).
6. **Twilio sync SDK blocking event loop** — asyncio.to_thread() in all Twilio outbound calls. ✅ Addressed.
7. **Module-level DI for Inngest functions** — _orchestrator var set in lifespan, not at import time. ✅ Addressed.
8. **OTel ALWAYS_ON vs ParentBasedTraceIdRatio** — ALWAYS_ON sampler configured. ✅ Addressed.

## Implications for Roadmap

## Phase Status

| Phase | Status | Completed |
|-------|--------|-----------|
| Phase 1: Infrastructure Foundation | ✅ Complete | 2026-03-06 |
| Phase 01.1: Apply revised 3NF schema | ✅ Complete | 2026-03-07 |
| Phase 2: GPT Extraction Service | ✅ Complete | ~2026-03-08 |
| Phase 02.1: Refactor persistence layer | ✅ Complete | 2026-03-08 |
| Phase 02.3: Migrate Jaeger to v2 | ✅ Complete | ~2026-03-08 |
| Phase 02.4: Prometheus setup | ✅ Complete | ~2026-03-08 |
| Phase 02.5: Production hardening | ✅ Complete | 2026-03-08 |
| Phase 3: Earnings Math Matching | ⏳ Next | — |
| Phase 4: End-to-End Integration & Deployment | ⏳ Future | — |

### Phase 3: Earnings Math Matching

Deterministic SQL matching query, ranked SMS formatter, empty-match handling. New module: `src/matches/service.py`. Integration point: PipelineOrchestrator WorkGoal branch. Key requirement: explicit NULL handling — exclude jobs with NULL pay_rate or NULL estimated_duration.

### Phase 4: End-to-End Integration & Deployment

STR-03 (job poster confirmation SMS), SEC-05 (STOP/START pass-through in Inngest process-message), DEP-03 (Render.com first production deploy validation). render.yaml Blueprint already exists (PROD-04 complete).

## Confidence Assessment

| Area | Confidence | Reason |
|------|------------|--------|
| Stack | HIGH | All packages in use; derived from actual pyproject.toml and codebase |
| Features | HIGH | REQUIREMENTS.md traceability table is authoritative; all ✅/⏳ items verified |
| Architecture | HIGH | STATE.md Architecture Snapshot is authoritative; all module names verified |
| Pitfalls | HIGH | Original pitfalls verified against implementation; new pitfalls derived from STATE.md Accumulated Context |

**Overall confidence:** HIGH — the system is built; all findings derive from the actual codebase and planning docs, not speculation.

### Gaps to Address

- **gpt-5.3-chat-latest model string:** The product owner specified `gpt-5.3-chat-latest`; this model name should be verified against OpenAI's current model catalog before Phase 3 execution (noted in STATE.md Blockers). The model IS in use and working; the concern is that the string may not be stable long-term.

## Sources

### Primary (HIGH confidence)
- `.planning/STATE.md` — Accumulated Context (40+ implementation decisions), Architecture Snapshot, What's Built
- `.planning/PROJECT.md` — Layer Stack, Key Modules, Data Model, Key Decisions, Constraints
- `.planning/REQUIREMENTS.md` — Full v1 requirement list with ✅/⏳ traceability table

### Secondary (MEDIUM confidence)
- `.planning/research/STACK.md`, `ARCHITECTURE.md`, `FEATURES.md`, `PITFALLS.md` — original pre-build research docs (now updated to match implemented state)

---
*Research updated: 2026-03-08*
*Ready for Phase 3 planning: yes*
