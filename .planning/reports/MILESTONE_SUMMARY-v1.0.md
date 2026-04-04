# Milestone v1.0 — Project Summary

**Generated:** 2026-04-04
**Purpose:** Team onboarding and project review

---

## 1. Project Overview

**Vici** is a Python/FastAPI API that connects job posters with workers entirely over SMS — no app, no signup, just text.

**Core value proposition:** A worker who texts their earnings goal receives a ranked list of jobs that lets them hit that goal in the shortest possible time.

**How it works:**
- Job posters text to create job listings. The system extracts structured fields (description, date/time, location, pay/rate) via GPT.
- Workers text their earnings target. The system matches them against available jobs using deterministic earnings math (`rate × duration ≥ target`) and replies with a ranked list.
- A single Twilio webhook handles all inbound messages. GPT classifies and extracts in a single structured call. Phone number is identity — first text auto-registers.

**Target users:** Gig workers seeking short-term jobs and job posters who want instant labor.

**Current status (v1.0):** 19 of 20 phases complete. The full pipeline is implemented and tested. Phase 4 (outbound SMS replies + Render.com deploy) is the only remaining work.

---

## 2. Architecture & Technical Decisions

### Request Path

```
SMS → Twilio → POST /webhook/sms
  └── 5-gate security chain (signature → idempotency → user → rate-limit → persist)
        └── Temporal ProcessMessageWorkflow start → HTTP 200

Temporal ProcessMessageWorkflow (4 retries, on_failure handler)
  └── PipelineOrchestrator.run()
        ├── ExtractionService → gpt-5.3-chat-latest (classify + extract, 1 call)
        ├── JobRepository | WorkGoalRepository (flush-only, single commit per branch)
        └── write_job_embedding() → Pinecone (fire-and-forget; failure enqueued)

Temporal SyncPineconeQueueWorkflow cron (*/5 * * * *)
  └── sync_pinecone_queue_activity — sweeps failed Pinecone writes
```

### Key Technical Decisions

- **Single webhook for all message types**
  - Why: Simplifies Twilio config; GPT classifier handles routing.
  - Phase: 1

- **GPT classifies + extracts in one `beta.chat.completions.parse` call**
  - Why: Reduces latency and token overhead vs. a two-step approach. Returns `JobExtraction | WorkerExtraction | UnknownMessage` discriminated union.
  - Phase: 2

- **Pinecone for vectors, not pgvector**
  - Why: External managed service; keeps PostgreSQL plain without vector extensions.
  - Phase: 2

- **ExtractionService is GPT-only; PipelineOrchestrator owns the full pipeline**
  - Why: Separation of concerns — ExtractionService is testable in isolation; orchestrator manages transactions.
  - Phase: 02.1

- **Flush-only repositories; caller controls transaction boundary**
  - Why: Single commit per pipeline branch prevents partial writes. Pinecone write fires after commit.
  - Phase: 02.1

- **Nested Pydantic Settings via `model_validator`**
  - Why: Clean per-domain namespacing (`settings.openai.api_key`) without changing the flat `.env` file.
  - Phase: 02.1

- **Temporal instead of Inngest for async processing**
  - Why: Temporal provides durable workflows with native retry logic, failure handlers, cron scheduling, and distributed tracing via TracingInterceptor. Inngest was replaced in Phase 02.9.
  - Phase: 02.9

- **ALWAYS_ON OTel sampler**
  - Why: Unambiguous full-coverage tracing; no parent-based override confusion.
  - Phase: 02.3

- **Chain of Responsibility handler pattern for pipeline branches**
  - Why: OCP — new message types can be added without modifying the orchestrator. Eliminates 3 inline if/elif branches.
  - Phase: 02.8.1

- **0/1 knapsack DP for earnings matching**
  - Why: Deterministic, fully testable, directly answers the worker's question. Earnings quantized to cents; DP capacity set to `max_possible_cents` (not capped at target) to allow single high-earning jobs to be selected.
  - Phase: 3

- **Render.com deployment (not Vercel)**
  - Why: Persistent server model; simpler than Vercel + ASGI adapter.
  - Phase: 02.5

- **Jaeger v2 + OpenSearch backend**
  - Why: Jaeger v1 all-in-one deprecated; v2 collector/query split with OpenSearch provides a production-grade trace store.
  - Phase: 02.3

---

## 3. Phases Delivered

| Phase | Name | Status | Summary |
|-------|------|--------|---------|
| 1 | Infrastructure Foundation | ✅ Complete | Async FastAPI skeleton, PostgreSQL, Alembic, 5-gate Twilio security, structlog/OTel/Prometheus, Inngest skeleton |
| 01.1 | Apply revised 3NF schema | ✅ Complete | Replaced Phone/InboundMessage/Worker with User/Message/WorkGoal using integer FKs |
| 2 | GPT Extraction Service | ✅ Complete | Single-call GPT classify+extract via `beta.chat.completions.parse`, Pinecone embedding write, audit log |
| 02.1 | Refactor persistence layer | ✅ Complete | PipelineOrchestrator, flush-only repos, nested Pydantic Settings, full DI graph in lifespan |
| 02.3 | Jaeger v2 migration | ✅ Complete | Jaeger v2 + OpenSearch, ALWAYS_ON sampler, manual spans on all uninstrumented pipeline steps |
| 02.4 | Prometheus setup | ✅ Complete | Prometheus + Grafana in Docker Compose, GPT token/latency metrics, auto-provisioned dashboard |
| 02.5 | Production hardening | ✅ Complete | Multi-stage Dockerfile, Temporal retries, sync_pinecone_queue sweep, render.yaml Blueprint, GitHub Actions CI |
| 02.6 | Research docs current | ✅ Complete | Updated 5 research docs (STACK, ARCHITECTURE, FEATURES, PITFALLS, SUMMARY) to match built system |
| 02.7 | README.md | ✅ Complete | Complete setup guide, env var reference, test instructions, deployment section |
| 02.8 | CLAUDE.md standards refactor | ✅ Complete | UserRepository extraction, EarlyReturn exception handler, Depends() refactor for SMS gates |
| 02.8.1 | SOLID principles refactor | ✅ Complete | Chain of Responsibility handlers, BaseRepository Template Method, eliminated 4× persist duplication |
| 02.9 | Inngest → Temporal migration | ✅ Complete | Full Temporal replacement: workflows, activities, worker, Docker Compose wiring |
| 02.10 | Temporal distributed tracing | ✅ Complete | TracingInterceptor on Temporal client, manual span on sync_pinecone_queue_activity |
| 02.11 | Edge-case hardening | ✅ Complete | 13 fixes: fail-fast config validation, GPT None guard, rolling rate limit, graceful shutdown |
| 02.12 | Simplify architecture | ✅ Complete | Domain boundaries canonicalized, module structure aligned to actual system |
| 02.13 | AGENTS.md standards refactor | ✅ Complete | GPT_MODEL DRY fix, pinecone_client.py → utils.py, _update_gauges extracted to module level |
| 02.13.1 | Distributed tracing gaps | ✅ Complete | OTel constants module, orchestrator/handler/router/activity span enrichment, PII fix, semconv fix |
| 02.14 | 3NF normalization | ✅ Complete | Dropped transitive user_id from job/work_goal, fixed rate_limit constraint, added audit_log CHECK |
| 3 | Earnings Math Matching | ✅ Complete | MatchService (0/1 knapsack DP), SMS formatter, MatchRepository (savepoint idempotency), 131 tests pass |
| **4** | **End-to-End Integration & Deployment** | **⏳ Not started** | Outbound SMS replies, STOP/START pass-through, Render.com live deploy |

---

## 4. Requirements Coverage

| Requirement | Description | Status |
|-------------|-------------|--------|
| SEC-01 | Twilio signature validation | ✅ 5-gate chain in sms/router.py |
| SEC-02 | MessageSid idempotency | ✅ MessageRepository with UNIQUE(message_sid) |
| SEC-03 | Rate limiting | ✅ Rolling-window rate limit via raw SQL |
| SEC-04 | Phone hash identity | ✅ Users identified by `sha256(phone)` stored as phone_hash |
| SEC-05 | STOP/START pass-through | ⏳ Phase 4 |
| EXT-01–04 | GPT classify + structured extraction | ✅ ExtractionService, discriminated union schemas |
| STR-01–02 | PostgreSQL storage for jobs and work_goals | ✅ JobRepository, WorkGoalRepository |
| STR-03 | Outbound SMS to poster and worker | ⏳ Phase 4 |
| VEC-01 | Pinecone embedding write for jobs | ✅ fire-and-forget with sync queue fallback |
| MATCH-01 | Earnings math matching (rate × duration ≥ target) | ✅ MatchService 0/1 knapsack DP |
| MATCH-02 | Ranked SMS formatter with poster phone | ✅ format_match_sms() |
| MATCH-03 | Graceful empty-match handling | ✅ is_empty + no-match message |
| OBS-01 | GPT call audit log | ✅ AuditLogRepository |
| OBS-02 | Prometheus + Grafana | ✅ metrics.py, Docker Compose provisioned |
| OBS-03 | Structured JSON logging | ✅ structlog throughout |
| OBS-04 | Distributed tracing | ✅ OTel → Jaeger v2 (OpenSearch), all pipeline spans covered |
| ASYNC-01 | Async FastAPI | ✅ asyncpg, async SQLAlchemy |
| ASYNC-02 | Temporal workflow orchestration | ✅ ProcessMessageWorkflow wired through Phase 3; Phase 4 wires matching + replies |
| ASYNC-03 | Pinecone sync queue cron | ✅ SyncPineconeQueueWorkflow (*/5 * * * *) |
| DEP-01 | Docker Compose local dev | ✅ 9 services: postgres, opensearch, jaeger-collector, jaeger-query, app, temporal, temporal-ui, prometheus, grafana |
| DEP-02 | render.yaml Blueprint | ✅ web service + PostgreSQL 16 basic-256mb |
| DEP-03 | Render.com production deploy | ⏳ Phase 4 |
| IDN-01 | 3NF schema (User/Message/WorkGoal integer FKs) | ✅ Phases 01.1 + 02.14 |

---

## 5. Key Decisions Log

| ID | Decision | Phase | Rationale |
|----|----------|-------|-----------|
| D-01 | Single Twilio webhook for all message types | 1 | Simpler Twilio config; classifier handles routing |
| D-02 | GPT classify + extract in one call | 2 | Eliminates two-step latency; discriminated union schema enforces type safety |
| D-03 | Pinecone (not pgvector) | 2 | Keeps postgres:16 plain; Pinecone is a managed service |
| D-04 | ExtractionService GPT-only; PipelineOrchestrator owns pipeline | 02.1 | SRP: testable extraction in isolation; orchestrator manages transactions |
| D-05 | Flush-only repositories, single commit per branch | 02.1 | Prevents partial writes; Pinecone fires after commit to avoid rollback coupling |
| D-06 | Nested Pydantic Settings | 02.1 | Namespaced config without .env changes |
| D-07 | ALWAYS_ON OTel sampler | 02.3 | Full trace coverage; no parent-based sampling confusion |
| D-08 | Jaeger v2 + OpenSearch | 02.3 | Production-grade trace store; v1 all-in-one deprecated |
| D-09 | Chain of Responsibility for pipeline handlers | 02.8.1 | OCP — new message types added without touching orchestrator |
| D-10 | BaseRepository Template Method | 02.8.1 | Eliminates 4× duplicated `session.add / flush / return` pattern |
| D-11 | Temporal (replacing Inngest) | 02.9 | Durable workflows, native retries, TracingInterceptor, cron scheduling |
| D-12 | TracingInterceptor on Client (not Worker) | 02.10 | Worker inherits interceptors automatically from client |
| D-13 | Lazy metric imports inside service methods | 02.4 | Avoids circular imports between metrics.py and service modules |
| D-14 | 0/1 knapsack DP for matching | 3 | Deterministic, testable, directly answers worker's earnings question |
| D-15 | DP capacity = max_possible_cents (not capped at target) | 3 | Allows a single high-earning job exceeding target to be selected |
| D-16 | begin_nested() savepoints for MatchRepository idempotency | 3 | Cross-dialect (PostgreSQL + SQLite) safe; only rolls back duplicate insert, not full session |
| D-17 | Render.com deployment | 02.5 | Persistent server; simpler than Vercel + ASGI adapter |
| D-18 | OTel constants in src/pipeline/constants.py | 02.13.1 | No magic attribute key strings per AGENTS.md |

---

## 6. Tech Debt & Deferred Items

### Minor Observations (from Phase 3 verification)

- `find_candidates_for_goal(session)` — SQL pre-filter selects all available jobs; DP applies the earnings target in Python. Intentional by design, but the SQL does not scope by work_goal fields.
- `MatchResult.is_partial=True` returned on empty results — `is_empty` property handles the distinction; formatter checks `is_empty` before `is_partial`. No behavioral impact.

### Known Gaps (Phase 4 not started)

- Outbound Twilio SMS replies to job posters (confirmation) and workers (match list) are not wired in Temporal workflow yet.
- STOP/START keyword pass-through to Twilio is not implemented.
- Render.com production deploy has never been executed — first live deploy validation is Phase 4.
- `GIT_SHA` env var on Render.com must be set manually or via deploy hooks (documented in render.yaml).

### Historical Architecture Decisions Superseded

- Inngest was the original async queue; fully replaced by Temporal in Phase 02.9. Historical plan descriptions reference Inngest but all runtime code uses Temporal.
- Phase 02.8 Plan 1 was superseded by Plan 2 after research confirmed several REFACTOR items were already implemented.

---

## 7. Getting Started

### Run the project locally

```bash
# 1. Clone and install dependencies
git clone <repo>
cd vici
cp .env.example .env  # fill in required secrets

# 2. Start all services (9 containers)
docker compose up

# 3. Apply migrations (if not using Docker init)
uv run alembic upgrade head
```

**Required secrets (`.env`):**
- `OPENAI_API_KEY` — OpenAI key for GPT extraction + embeddings
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` — Twilio credentials
- `PINECONE_API_KEY`, `PINECONE_INDEX_NAME` — Pinecone serverless index
- `DATABASE_URL` — PostgreSQL connection string
- `TEMPORAL_HOST` — Temporal server address

### Run tests

```bash
uv run pytest tests/ -x -q
# Expected: 131 passed, 1 skipped
```

### Key directories

```
src/
├── sms/           # Webhook route + 5-gate security chain
├── extraction/    # ExtractionService (GPT), PipelineOrchestrator, Pinecone
├── pipeline/      # Chain of Responsibility handlers + constants
├── temporal/      # Workflows, activities, worker runner
├── matches/       # MatchService, MatchRepository, SMS formatter
├── jobs/          # JobRepository, Job model
├── work_goals/    # WorkGoalRepository, WorkGoal model
├── users/         # UserRepository, User model
├── config.py      # Nested Pydantic Settings (4 sub-models)
├── metrics.py     # Prometheus singletons
└── main.py        # FastAPI app + lifespan DI graph
```

### Where to look first

- **Entry point:** `src/main.py` — lifespan builds the full DI graph
- **Webhook handler:** `src/sms/router.py` — 5-gate security chain
- **Core pipeline:** `src/pipeline/orchestrator.py` — GPT → storage → Pinecone
- **Temporal workflows:** `src/temporal/workflows.py` + `activities.py`
- **Matching logic:** `src/matches/service.py` — MatchService with DP

### Local observability

| Service | URL |
|---------|-----|
| FastAPI docs | http://localhost:8000/docs |
| Jaeger traces | http://localhost:16686 |
| Temporal UI | http://localhost:8080 |
| Grafana dashboards | http://localhost:3000 |
| Prometheus | http://localhost:9090 |

---

## Stats

- **Timeline:** 2026-03-06 → 2026-04-04 (29 days)
- **Phases:** 19 / 20 complete (Phase 4 not started)
- **Plans:** 32 / 32 complete
- **Commits:** 307
- **Files changed:** 494 (+74,973 / −1,222)
- **Contributors:** Andrew Carpenter
