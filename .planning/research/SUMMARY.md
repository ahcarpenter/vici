# Project Research Summary

**Project:** Vici
**Domain:** SMS-based job matching API (gig economy / labor marketplace via Twilio)
**Researched:** 2026-03-05
**Confidence:** MEDIUM — web research tools unavailable; findings from training knowledge (cutoff Aug 2025). Architecture and pitfalls confidence HIGH; stack version pins and feature landscape MEDIUM.

## Executive Summary

Vici is an SMS-first gig labor marketplace that matches workers to jobs based on earnings math rather than search. The recommended implementation approach is a Python/FastAPI async monolith with a layered architecture: a single Twilio webhook endpoint receives inbound SMS, a combined GPT classify-and-extract call produces structured job or worker-goal data, and a deterministic earnings-math query ranks and returns matching jobs via outbound SMS. The entire stack — FastAPI, SQLAlchemy 2.0 async, asyncpg, pgvector, Alembic, Twilio SDK, openai SDK — is a mature, well-documented combination with established patterns. No novel integration challenges exist at v1 scale.

The key architectural decision is to return HTTP 200 to Twilio immediately (via FastAPI `BackgroundTasks`) and process the GPT call and DB writes out-of-band, sending the SMS reply via the Twilio REST API rather than a TwiML response. This is required because GPT latency can exceed Twilio's 15-second webhook timeout under realistic conditions. The schema should include a pgvector `embedding` column (NULL in v1) and HNSW index from day one to avoid a costly migration when semantic matching is added later.

The top risks are all known anti-patterns with reliable prevention: Twilio signature validation silently broken by reverse proxy URL mismatch (fix: use a `WEBHOOK_BASE_URL` env var), Twilio retry-triggered duplicates (fix: idempotency on `MessageSid` before any processing), GPT hallucinating structured fields (fix: OpenAI structured outputs with Pydantic schema, not JSON mode), and synchronous DB calls blocking the async event loop (fix: SQLAlchemy async from day one). None of these are novel — they are well-documented traps with standard mitigations.

## Key Findings

### Recommended Stack

The stack is a standard Python async API stack with three external integrations: Twilio (inbound/outbound SMS), OpenAI (GPT classify + extract), and PostgreSQL with pgvector (data + future semantic search). Python 3.12 with FastAPI 0.111+, SQLAlchemy 2.0 async via asyncpg, and Alembic for migrations is the canonical combination for this type of project. `uv` replaces pip/poetry as the dependency manager. See `.planning/research/STACK.md` for full version matrix and compatibility notes.

**Core technologies:**
- **Python 3.12 + FastAPI 0.111**: Runtime and HTTP framework — native async, automatic OpenAPI docs, Pydantic v2 integration
- **SQLAlchemy 2.0 async + asyncpg**: ORM and database driver — non-blocking DB I/O; required to avoid event loop blocking
- **PostgreSQL 16 + pgvector 0.7+**: Primary datastore + vector search — managed pgvector support on Railway/Neon; HNSW index for future semantic matching
- **Alembic 1.13**: Schema migrations — first-class SQLAlchemy 2.0 async support
- **openai SDK 1.30+ (AsyncOpenAI)**: GPT classify+extract — structured outputs via `beta.chat.completions.parse()` with Pydantic schema
- **twilio SDK 9.x**: Inbound signature validation + outbound SMS — wrap sync REST client in `asyncio.to_thread()`
- **tenacity**: Retry logic for OpenAI calls — exponential backoff for rate limits and transient errors
- **structlog**: Structured JSON logging — per-request context (phone, message_id) required for production observability

**Version flags:** The `gpt-5.3-chat-latest` model string, openai SDK 1.30 pin, twilio SDK 9.x, and pgvector-python 0.3 should all be verified against current releases before `uv add` — web access was unavailable during research.

### Expected Features

The feature set is well-defined with a clear v1/v1.x/v2 split. The entire v1 feature set can be delivered as a single coherent vertical slice. See `.planning/research/FEATURES.md` for full prioritization matrix and dependency graph.

**Must have (table stakes):**
- Twilio X-Twilio-Signature validation — security baseline; no production deploy without it
- MessageSid idempotency — prevents duplicate job posts from Twilio retries; cheap to build early, expensive to retrofit
- Rate limiting per phone number — prevents GPT/Twilio cost blowout from loops or abuse
- Phone number as identity (auto-registration) — zero-friction onboarding is the core UX promise
- Single-call GPT classification + extraction — job post vs. worker goal with structured field output
- Earnings math matching: `rate * duration >= goal`, sorted by soonest/shortest
- SMS confirmation reply to job poster with extracted fields summarized
- SMS ranked job list reply to worker (condensed format, 3-5 results)
- STOP/START keyword pass-through — Twilio compliance requirement
- Graceful fallback for unclassifiable messages

**Should have (competitive differentiators):**
- Earnings math matching transparency — workers understand why they got results
- Time-of-send context inference for relative datetime expressions ("tomorrow morning")
- Field-level confidence with clarification prompts — improves extraction quality
- SMS query commands ("MY JOBS", "CANCEL JOB 2") for poster management

**Defer (v2+):**
- Semantic / pgvector matching — schema-ready in v1; feature deferred until earnings-math matching is validated
- Async processing with task queue (Celery/ARQ) — defer unless GPT p95 consistently breaches 10s in production
- Web dashboard — defer until SMS channel is validated
- Multi-turn conversation state / dialog management

**Key dependency:** Twilio signature validation and MessageSid idempotency must be the first two things implemented — they are security and correctness gates for everything else.

### Architecture Approach

The recommended architecture is a four-layer monolith: API layer (FastAPI routes, Twilio validation, TwiML response), Service layer (MessageService orchestrator, ExtractionService, MatchService), Repository layer (PhoneRepository, JobRepository, WorkerRepository), and Data layer (PostgreSQL + pgvector). Business logic belongs exclusively in services and repositories — routes call services and return responses, nothing more. The background task pattern (`FastAPI.BackgroundTasks`) decouples Twilio's response window from GPT processing without requiring a queue at v1 scale. See `.planning/research/ARCHITECTURE.md` for full component diagram, data flow, and build order.

**Major components:**
1. **Webhook route (`POST /webhook/sms`)** — validates Twilio signature, returns empty TwiML 200 immediately, enqueues background task
2. **MessageService** — orchestrates the full flow: phone identity resolution → GPT classify+extract → store → match → send reply via Twilio REST
3. **ExtractionService** — single GPT call returning a discriminated union `JobExtraction | WorkerExtraction | UnknownMessage`
4. **MatchService + JobRepository** — earnings math query in SQL (`rate * duration >= goal`), Python-level sort by recency/duration
5. **PhoneRepository** — get-or-create identity; phone number is the only identity token
6. **Alembic migrations** — initial migration creates `phone_numbers`, `jobs`, `workers` tables, `CREATE EXTENSION vector`, and HNSW index on `jobs.embedding`

### Critical Pitfalls

See `.planning/research/PITFALLS.md` for full detail including phase-to-pitfall mapping, recovery costs, and verification checklists.

1. **Twilio signature validation broken by reverse proxy URL mismatch** — Set `WEBHOOK_BASE_URL` as an env var and reconstruct the URL from config; enable Uvicorn `--proxy-headers`; test in CI by replaying a real Twilio payload with a known-bad signature and confirming HTTP 403.
2. **Webhook timeout causing Twilio retries and duplicate processing** — Return HTTP 200 immediately with empty TwiML; process GPT+DB in `BackgroundTasks`; deduplicate on `MessageSid` with a unique constraint before any processing.
3. **GPT hallucinating structured fields** — Use OpenAI structured outputs (JSON schema enforcement) not JSON mode; make all optional fields explicitly nullable with "return null if not present" in the prompt; validate through Pydantic `ExtractionResult` discriminated union before any downstream use.
4. **Synchronous SQLAlchemy in async FastAPI handlers** — Use `create_async_engine` + `AsyncSession` + asyncpg from day one; never use the sync session in `async def` handlers; verify with a 10-concurrent-request test early.
5. **Missing raw message audit trail** — Store raw SMS body and raw GPT response in a `raw_messages` table from the start; data that isn't logged can never be recovered; this is cheap storage with high debugging value.

## Implications for Roadmap

Research strongly suggests a 4-phase build that follows the architecture's natural dependency order: infrastructure before domain logic, domain logic before integration, integration before polish.

### Phase 1: Infrastructure Foundation

**Rationale:** Every other component depends on a running database, async DB session management, and Twilio signature validation. These are not features — they are the foundation that makes all features testable. Building these wrong (sync SQLAlchemy, no signature validation, missing idempotency) requires full refactors later.
**Delivers:** A deployable API skeleton with a health endpoint, Alembic migrations (including pgvector extension + HNSW index), async DB session via dependency injection, Twilio signature validation middleware, MessageSid idempotency table, rate limiting, and structured logging.
**Addresses:** Phone-as-identity (auto-registration), HTTPS-only deployment, raw message audit table
**Avoids (critical):** Pitfalls 1 (signature validation), 2 (webhook timeout/idempotency), 6 (sync DB in async handler), 7 (pgvector index missing), 8 (no rate limiting), 10 (no audit trail), 3 (phone recycling — `created_at` in schema)
**Research flag:** Standard patterns — skip `/gsd:research-phase`. All components are well-documented FastAPI + SQLAlchemy + Twilio conventions.

### Phase 2: GPT Extraction Service

**Rationale:** Extraction is the most uncertain component (prompt engineering, schema design, validation logic). It must be developed and tested in isolation before being wired into the orchestration flow. Classification accuracy determines the entire downstream correctness of the system.
**Delivers:** `ExtractionService` with single GPT call returning validated `JobExtraction | WorkerExtraction | UnknownMessage` Pydantic discriminated union; prompt engineering for structured outputs; handling of null fields, ambiguous messages, and extraction failures; fallback SMS reply for unknown/unclassifiable messages.
**Implements:** ExtractionService, Pydantic extraction schemas, OpenAI async client, tenacity retry wrapper
**Avoids (critical):** Pitfalls 4 (GPT hallucination), 5 (missing classification checkpoint)
**Research flag:** May benefit from `/gsd:research-phase` specifically for: gpt-5.3-chat-latest structured output behavior (model string validation), optimal prompt structure for discriminated union extraction, token budget estimation.

### Phase 3: Earnings Math Matching

**Rationale:** Matching logic is deterministic and self-contained. Once the extraction schemas are defined (Phase 2), the matching query can be written and tested against seeded DB data without needing live GPT calls or Twilio. Null handling in SQL must be explicit and tested before integration.
**Delivers:** `MatchService.find_matches()`, `JobRepository.find_matching()` with SQL earnings math query and explicit null handling, Python-level sort by soonest/shortest, ranked job list SMS formatting (condensed, 3-5 results, 160-char constraints).
**Implements:** MatchService, JobRepository matching query, earnings math SQL with CASE/NULLIF null handling
**Avoids (critical):** Pitfall 9 (null handling in earnings math)
**Research flag:** Standard patterns — skip `/gsd:research-phase`. Pure SQL + Python logic with well-understood semantics.

### Phase 4: End-to-End Integration and Observability

**Rationale:** Wire all components together through MessageService orchestration, add the background task pattern to meet Twilio's timeout constraint, implement outbound SMS via Twilio REST API, and harden observability. This is also where UX edge cases (empty match lists, SMS length limits, STOP/START compliance) are tested end-to-end.
**Delivers:** `MessageService.process()` full orchestration (identity → extract → store → match → reply), background task wiring, outbound SMS via Twilio REST client (wrapped in `asyncio.to_thread()`), SMS confirmation to job posters with extracted fields, SMS ranked results to workers, empty-match-list reply, STOP/START pass-through, structured logging with request ID propagation, error surfaces (GPT failure, DB failure, validation failure), deployment config (Docker Compose, Railway/Fly.io).
**Avoids (critical):** Pitfalls 2 (background task session scoping — background tasks must create their own DB sessions), 5 (sync Twilio SDK in async handler)
**Research flag:** Standard patterns — skip `/gsd:research-phase`. Background task session scoping and Twilio async patterns are well-documented.

### Phase Ordering Rationale

- **Infrastructure first** — Async DB setup, signature validation, idempotency, and schema (including pgvector + audit table) must exist before any feature work. Retrofitting these is HIGH recovery cost (full refactor for async DB, data loss for missing audit trail).
- **Extraction before matching** — MatchService depends on the Pydantic schemas defined in ExtractionService. Extraction schemas are also the hardest component to get right (prompt engineering), so they need the most iteration time.
- **Matching before integration** — Matching logic should be tested in isolation against seeded data before being wired to live GPT + Twilio. Null handling bugs are much easier to catch in unit tests than in end-to-end flows.
- **Integration last** — The orchestration layer (MessageService + background tasks) is glue code; it's fast to write once the underlying components are solid and tested.

### Research Flags

Phases likely needing `/gsd:research-phase` during planning:
- **Phase 2 (GPT Extraction):** gpt-5.3-chat-latest model string needs verification against OpenAI's current model naming; structured output behavior for discriminated union schemas should be validated; token budget for system prompt + schema + SMS body needs measurement before choosing sync vs. background approach.

Phases with standard patterns (can skip `/gsd:research-phase`):
- **Phase 1 (Infrastructure):** FastAPI + SQLAlchemy 2.0 async + Alembic patterns are stable and extensively documented; Twilio signature validation is a well-known pattern.
- **Phase 3 (Matching):** Deterministic SQL logic; no novel patterns.
- **Phase 4 (Integration):** Background task session scoping and Twilio async wrapper (`asyncio.to_thread`) are standard FastAPI patterns.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM | Core patterns (FastAPI, SQLAlchemy async, asyncpg) are HIGH confidence; version pins for openai SDK, twilio SDK, pgvector-python are MEDIUM — verify against PyPI before lockfile |
| Features | MEDIUM | Twilio security/idempotency/phone-identity patterns are HIGH confidence; gpt-5.3-chat-latest model specifics and SMS marketplace landscape are MEDIUM (training knowledge, no live competitor research) |
| Architecture | HIGH | All architectural patterns are stable, mature conventions for this stack combination; four-layer separation and background task pattern are well-established |
| Pitfalls | HIGH | All 10 pitfalls are well-documented community patterns with official documentation backing; recovery cost assessments are based on standard refactoring estimates |

**Overall confidence:** MEDIUM-HIGH — the architecture and pitfall mitigations are reliable. The main uncertainty is around specific version pins and gpt-5.3-chat-latest model behavior, both of which are easily verified at implementation time.

### Gaps to Address

- **gpt-5.3-chat-latest model string:** The product owner specified `gpt-5.3-chat-latest`; this model name should be verified against OpenAI's current model catalog before Phase 2. If the string is incorrect, use the closest available GPT model with structured output support.
- **openai SDK 1.30 structured outputs:** `beta.chat.completions.parse()` is the recommended pattern for typed structured outputs; verify this endpoint is still in beta vs. stable in the current SDK version.
- **Twilio SDK 9.x:** Verify 9.x is the current major version; the 8.x → 9.x upgrade dropped Python 3.7 support but the API is otherwise similar.
- **pgvector-python 0.3:** Verify SQLAlchemy 2.0 `TypeDecorator` support is in this version; the HNSW index in the initial migration is the priority regardless of client version.
- **Rate limiting strategy:** Research recommends PostgreSQL-backed counters (no Redis dependency at v1); if a Redis instance is already available in the deployment environment, the Redis counter approach is simpler and more standard. Confirm deployment platform before choosing.

## Sources

### Primary (HIGH confidence)
- FastAPI official docs — async routes, dependency injection, BackgroundTasks patterns
- SQLAlchemy 2.0 async docs — AsyncSession, async_sessionmaker, asyncpg integration
- Twilio webhook security docs — X-Twilio-Signature HMAC validation, retry behavior, 15-second timeout
- pgvector GitHub README — HNSW vs. IVFFlat recommendation, SQLAlchemy TypeDecorator
- Alembic async cookbook — run_sync pattern for async engine in env.py
- OpenAI Python SDK — AsyncOpenAI, structured outputs via json_schema response_format

### Secondary (MEDIUM confidence)
- Training knowledge of Twilio SMS marketplace patterns — feature landscape, idempotency requirements
- Training knowledge of OpenAI structured outputs (gpt-5.3-chat-latest specifics beyond Aug 2025 cutoff)
- Adjacent gig marketplace feature analysis (Wonolo, Instawork, Snagajob) — inferential

### Tertiary (LOW confidence — validate during implementation)
- gpt-5.3-chat-latest model string — verify against OpenAI model catalog at implementation time
- Twilio SDK 9.x as current major version — verify on PyPI
- pgvector-python 0.3 SQLAlchemy 2.0 compatibility — verify on PyPI

---
*Research completed: 2026-03-05*
*Ready for roadmap: yes*
