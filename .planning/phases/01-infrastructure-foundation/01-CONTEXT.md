# Phase 1: Infrastructure Foundation - Context

**Gathered:** 2026-03-05
**Updated:** 2026-03-07
**Status:** Complete — schema updated via 3NF review

<domain>
## Phase Boundary

A deployable, secure async API skeleton exists with full observability, database schema, async session management, Twilio signature validation, idempotency, rate limiting, and Inngest event emission — so every subsequent phase builds on a correct, tested foundation. Creating or processing messages is out of scope; this phase only receives, validates, and hands off.

</domain>

<decisions>
## Implementation Decisions

### Project Layout
- Domain-based `src/` structure per AGENTS.md conventions (not file-type layers)
- Domains: `src/sms/` (webhook), `src/jobs/`, `src/workers/` — each with router.py, schemas.py, models.py, service.py, dependencies.py, constants.py, exceptions.py, utils.py
- Global files: `src/config.py`, `src/database.py`, `src/main.py`, `src/exceptions.py`, `src/models.py`
- Import convention: explicit module names across domains (`from src.sms import service as sms_service`)
- Migrations in top-level `migrations/` (Alembic), tests in top-level `tests/`

### Database Schema (3NF — revised 2026-03-07)

All tables use TIMESTAMPTZ (not TIMESTAMP) for all datetime columns. All inter-table relationships use integer FK to the primary key of the referenced table with ON DELETE RESTRICT unless noted otherwise.

**`user`**
- `id` SERIAL PK
- `phone_hash` VARCHAR UNIQUE NOT NULL — SHA-256 of E.164-normalized phone number
- `created_at` TIMESTAMPTZ NOT NULL

**`message`** (replaces `inbound_message`)
- `id` SERIAL PK
- `message_sid` VARCHAR UNIQUE NOT NULL — Twilio SID; idempotency key
- `user_id` INTEGER NOT NULL REFERENCES user(id) ON DELETE RESTRICT
- `body` TEXT NOT NULL — SMS text content (raw_sms column dropped; body is the single copy)
- `message_type` VARCHAR NULL — NULL until GPT classifies; then `job_posting | work_request | unknown`
- `raw_gpt_response` TEXT NULL — populated after GPT call in Phase 2
- `created_at` TIMESTAMPTZ NOT NULL

**`job`**
- `id` SERIAL PK
- `user_id` INTEGER NOT NULL REFERENCES user(id) ON DELETE RESTRICT
- `message_id` INTEGER NOT NULL UNIQUE REFERENCES message(id) ON DELETE RESTRICT — 1:1 with source message
- `description` TEXT NULL
- `location` TEXT NULL
- `pay_rate` FLOAT NOT NULL CHECK (pay_rate > 0)
- `estimated_duration_hours` FLOAT NULL CHECK (estimated_duration_hours > 0)
- `ideal_datetime` TIMESTAMPTZ NULL — NULL if GPT cannot produce a parseable datetime
- `datetime_flexible` BOOLEAN NULL
- `created_at` TIMESTAMPTZ NOT NULL

**`work_request`** (replaces `worker`)
- `id` SERIAL PK
- `user_id` INTEGER NOT NULL REFERENCES user(id) ON DELETE RESTRICT
- `message_id` INTEGER NOT NULL UNIQUE REFERENCES message(id) ON DELETE RESTRICT — 1:1 with source message
- `target_earnings` FLOAT NOT NULL CHECK (target_earnings > 0)
- `target_timeframe` TEXT NULL
- `created_at` TIMESTAMPTZ NOT NULL

**`match`**
- `id` SERIAL PK
- `job_id` INTEGER NOT NULL REFERENCES job(id) ON DELETE RESTRICT
- `work_request_id` INTEGER NOT NULL REFERENCES work_request(id) ON DELETE RESTRICT
- `matched_at` TIMESTAMPTZ NOT NULL
- UNIQUE (job_id, work_request_id) — a pair is matched at most once
- Note: both users are derivable via JOIN (job→user, work_request→user); no denormalized user_id columns per 3NF

**`rate_limit`**
- `id` SERIAL PK
- `user_id` INTEGER NOT NULL REFERENCES user(id) ON DELETE RESTRICT
- `window_start` TIMESTAMPTZ NOT NULL
- `count` INTEGER NOT NULL DEFAULT 0
- UNIQUE (user_id, window_start)

**`audit_log`**
- `id` SERIAL PK
- `message_sid` VARCHAR NOT NULL — Twilio SID present even for pre-persistence events (rate limit rejections)
- `message_id` INTEGER NULL REFERENCES message(id) ON DELETE SET NULL — NULL for events before message row exists
- `event` VARCHAR NOT NULL
- `detail` TEXT NULL
- `created_at` TIMESTAMPTZ NOT NULL

### Schema Constraints (all tables)
- All datetime columns: TIMESTAMPTZ, not TIMESTAMP
- All FK relationships: ON DELETE RESTRICT unless noted (audit_log.message_id uses SET NULL)
- Numeric extraction fields with a natural lower bound have CHECK (value > 0)
- No default values on application-supplied fields (only DB defaults: id, created_at)

### ORM / Database
- SQLModel (Pydantic-native, SQLAlchemy under the hood) — not SQLAlchemy directly
- Separate models per domain: `models.py` contains SQLModel `table=True` classes; `schemas.py` contains Pydantic `BaseModel` for API request/response
- Alembic autogenerate from SQLModel metadata — import all domain models in `migrations/env.py` before running autogenerate
- No pgvector extension — Pinecone handles all vector storage; PostgreSQL stays vanilla
- Alembic migration file naming: `YYYY-MM-DD_slug.py` format per AGENTS.md

### Observability
- Jaeger (`jaegertracing/all-in-one`) added to Docker Compose — UI at `http://localhost:16686`, OTLP gRPC at port 4317
- App connects via `OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317`
- Trace context propagated across async handoff by injecting W3C `traceparent` into Inngest event payload; Inngest function extracts it and starts a child span
- structlog integrated with OTel: custom processor auto-injects `trace_id` and `span_id` from active span into every log line — OBS-04 trace_id requirement is met automatically

### Rate Limiting
- Threshold: 5 messages per minute per user
- rate_limit table keyed on user_id + window_start (1-minute buckets) — upsert increments count
- On breach: return HTTP 200 with empty TwiML body — Twilio won't retry on 200
- Webhook security gate order (cheapest to most expensive):
  1. Twilio signature validation (crypto only, no DB) → 403 on failure
  2. message_sid idempotency check (one DB read on message table) → empty TwiML 200 on duplicate
  3. Rate limit check (upsert on rate_limit table using user_id) → empty TwiML 200 on breach
  4. Fire Inngest `message.received` event → return HTTP 200

### Claude's Discretion
- Exact Prometheus metric names and histogram bucket boundaries
- Phone number hashing algorithm (SHA-256 of E.164 normalized number)
- Inngest `process-message` stub body (just a log statement in Phase 1)
- Docker Compose health check configuration details

</decisions>

<specifics>
## Specific Ideas

- AGENTS.md is the authoritative FastAPI style guide for this project — all code must follow those conventions (async route rules, dependency chaining, database naming, Alembic config, ruff linting)
- Rate limiting uses PostgreSQL to avoid Redis as an infrastructure dependency at v1 scale
- The `rate_limit` table uses lazy cleanup: stale rows from prior windows are deleted on the next request from that user, not by a cron job
- `message.message_type` is NULL at row creation; Phase 2 ExtractionService updates it after GPT classification. NULL means "not yet processed."
- `job.ideal_datetime` stores TIMESTAMPTZ when parseable; NULL when GPT returns a relative or ambiguous time ("tomorrow morning"). Raw body is always recoverable from `message.body`.
- The `match` table is the join point for MATCH-01 earnings math queries (Phase 3). Users are always derivable via `match → job → user` and `match → work_request → user`.

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/config.py` — `Settings(BaseSettings)` with `@lru_cache`; add new env vars here for Phase 2 (OPENAI_API_KEY, PINECONE_API_KEY, PINECONE_INDEX_HOST, BRAINTRUST_API_KEY)
- `src/database.py` — async SQLAlchemy session factory; all Phase 2 repositories use the same session pattern
- `src/jobs/models.py`, `src/workers/models.py` — SQLModel table classes; will need renaming/updating to match new schema (worker → work_request)

### Established Patterns
- AGENTS.md defines all conventions: domain-based structure, async route rules, dependency chaining, Pydantic validators, DB naming, ruff linting
- SQLite + aiosqlite for test DB — no postgres dependency in unit tests
- `expire_on_commit=False` on async_sessionmaker — required for async SQLAlchemy
- `autouse _auto_mock_inngest_send` fixture in conftest — prevents real Inngest HTTP calls in all tests

### Integration Points
- Docker Compose: PostgreSQL 16 + Inngest Dev Server + Jaeger — all start together via `docker compose up`
- Alembic runs migrations before API starts; new migration needed for schema rework (rename tables, add FKs, add match table, TIMESTAMPTZ columns)
- Inngest Dev Server receives events at its local endpoint

</code_context>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 01-infrastructure-foundation*
*Context gathered: 2026-03-05 | Schema updated: 2026-03-07 via 3NF review*
