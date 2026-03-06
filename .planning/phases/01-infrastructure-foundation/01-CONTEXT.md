# Phase 1: Infrastructure Foundation - Context

**Gathered:** 2026-03-05
**Status:** Ready for planning

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

### ORM / Database
- SQLModel (Pydantic-native, SQLAlchemy under the hood) — not SQLAlchemy directly
- Separate models per domain: `models.py` contains SQLModel `table=True` classes; `schemas.py` contains Pydantic `BaseModel` for API request/response (never expose raw internal fields like `raw_sms` in API responses)
- Alembic autogenerate from SQLModel metadata — import all domain models in `migrations/env.py` before running autogenerate
- No pgvector extension — Pinecone handles all vector storage; PostgreSQL stays vanilla
- Alembic migration file naming: `YYYY-MM-DD_slug.py` format per AGENTS.md

### Observability
- Jaeger (`jaegertracing/all-in-one`) added to Docker Compose — UI at `http://localhost:16686`, OTLP gRPC at port 4317
- App connects via `OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317`
- Trace context propagated across async handoff by injecting W3C `traceparent` into Inngest event payload; Inngest function extracts it and starts a child span
- structlog integrated with OTel: custom processor auto-injects `trace_id` and `span_id` from active span into every log line — OBS-04 trace_id requirement is met automatically, not manually

### Rate Limiting
- Threshold: 5 messages per minute per phone number
- PostgreSQL TTL counter: dedicated `rate_limit` table with columns `(phone_hash, window_start, count)` — upsert increments count per 1-minute bucket
- On breach: return HTTP 200 with empty TwiML body — Twilio won't retry on 200; no SMS sent to abuser
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

</decisions>

<specifics>
## Specific Ideas

- AGENTS.md is the authoritative FastAPI style guide for this project — all code must follow those conventions (async route rules, dependency chaining, database naming, Alembic config, ruff linting)
- Rate limiting uses PostgreSQL to avoid Redis as an infrastructure dependency at v1 scale (explicit design decision from REQUIREMENTS.md)
- The `rate_limit` table uses lazy cleanup: stale rows from prior windows are deleted on the next request from that phone, not by a cron job

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- None — greenfield project. No existing components, hooks, or utilities.

### Established Patterns
- AGENTS.md defines all conventions: domain-based structure, async route rules, dependency chaining, Pydantic validators, DB naming, ruff linting
- These patterns apply to all code written in Phases 1–4

### Integration Points
- Docker Compose: PostgreSQL 16 + Inngest Dev Server + Jaeger — all must start together via `docker compose up`
- Alembic runs migrations against PostgreSQL before API starts
- Inngest Dev Server receives events at its local endpoint; API connects to it in local dev

</code_context>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 01-infrastructure-foundation*
*Context gathered: 2026-03-05*
