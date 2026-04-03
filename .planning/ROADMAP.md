# Roadmap: Vici

## Overview

Vici is built in phases that follow a strict dependency order: infrastructure before domain logic, domain logic before integration, integration before deployment. Phase 1 lays the async foundation (DB, schema, security, observability, Inngest skeleton). The inserted decimal phases (01.1, 02.1, 02.3, 02.4, 02.5) addressed schema normalization, architecture refactors, and production hardening before moving forward. Phase 3 adds deterministic earnings-math matching. Phase 4 wires all components end-to-end and ships to Render.com.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3, 4): Planned milestone work
- Decimal phases (1.1, 2.1, 2.3, 2.4, 2.5): Urgent insertions (marked INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Infrastructure Foundation** - Async API skeleton, schema migrations, security gates, observability, and Inngest event wiring (completed 2026-03-06)
- [x] **Phase 01.1: Apply revised 3NF schema** - Normalize schema to User/Message/WorkRequest with integer FKs (completed 2026-03-07)
- [x] **Phase 2: GPT Extraction Service** - Single-call GPT classify+extract pipeline with Pydantic schemas, Pinecone write, and storage (completed ~2026-03-08)
- [x] **Phase 02.1: Refactor persistence layer and service boundaries** - Clean DI graph, PipelineOrchestrator, flush-only repositories (completed 2026-03-08)
- [x] **Phase 02.3: Migrate Jaeger to v2 and optimize tracing setup** - Jaeger v2 + OpenSearch, ALWAYS_ON sampler, manual spans (completed ~2026-03-08)
- [x] **Phase 02.4: Ensure Prometheus is setup** - Prometheus + Grafana in Docker Compose, custom GPT metrics, auto-provisioning (completed ~2026-03-08)
- [x] **Phase 02.5: Production hardening** - Multi-stage Dockerfile, Inngest retries, sync_pinecone_queue sweep, render.yaml, GitHub Actions CI, test coverage audit (completed 2026-03-08)
- [ ] **Phase 3: Earnings Math Matching** - Deterministic SQL matching query, ranked SMS formatter, and empty-match handling
- [ ] **Phase 4: End-to-End Integration & Deployment** - Inngest orchestration function fully wired, outbound SMS replies, STOP/START compliance, and Render.com production deploy

## Phase Details

### Phase 1: Infrastructure Foundation
**Goal**: A deployable, secure API skeleton exists with full observability, database schema, async session management, Twilio signature validation, idempotency, rate limiting, and Inngest event emission — so every subsequent phase builds on a correct, tested foundation
**Depends on**: Nothing (first phase)
**Requirements**: SEC-01, SEC-02, SEC-03, SEC-04, IDN-01, IDN-02, OBS-02, OBS-03, OBS-04, ASYNC-01, ASYNC-03, DEP-01, DEP-02
**Success Criteria** (what must be TRUE):
  1. A POST to `/webhook/sms` with an invalid Twilio signature returns HTTP 403; a valid signature returns HTTP 200 and emits an Inngest `message.received` event without blocking
  2. Sending the same Twilio MessageSid twice results in only one database record; the second request is silently dropped before any processing
  3. The `/health` endpoint returns service status and the `/metrics` endpoint returns Prometheus-formatted counters and histograms
  4. Every inbound request produces a structured JSON log line containing phone hash, message_id, and trace_id; OTel spans appear in the collector from webhook receipt through Inngest event emission
  5. `docker compose up` starts PostgreSQL, applies all Alembic migrations, and runs the Inngest Dev Server alongside the API
**Status**: Complete (2026-03-06)
**Plans:** 3/3 complete

Plans:
- [x] 01-01-PLAN.md — Project scaffold, Docker Compose (postgres:16 + Inngest Dev Server), Alembic migrations, async DB session
- [x] 01-02-PLAN.md — Twilio signature validation, MessageSid idempotency, rate limiting, audit table, phone identity
- [x] 01-03-PLAN.md — Observability stack (structlog, OTel, Prometheus), Inngest client + event emission, health endpoint

### Phase 01.1: Apply revised 3NF schema and propagate throughout app (INSERTED)

**Goal:** Replace Phone/InboundMessage/Worker with User/Message/WorkRequest using integer FKs; eliminate phone_hash string pseudo-FKs throughout the app
**Requirements**: IDN-01 (schema normalization), all repositories updated
**Depends on:** Phase 1
**Status**: Complete (2026-03-07)
**Plans:** 2/2 complete

Plans:
- [x] 01.1-01-PLAN.md — Alembic migration, User/Message/WorkRequest SQLModels, updated repositories
- [x] 01.1-02-PLAN.md — Propagate schema changes through all services, tests, and fixtures

### Phase 2: GPT Extraction Service
**Goal**: A tested ExtractionService exists that accepts raw SMS text and returns a validated `JobExtraction | WorkerExtraction | UnknownMessage` discriminated union, stores results in PostgreSQL, and writes job embeddings to Pinecone — so Phase 3 can query against real structured data
**Depends on**: Phase 01.1
**Requirements**: EXT-01, EXT-02, EXT-03, EXT-04, STR-01, STR-02, VEC-01, OBS-01
**Status**: Complete (~2026-03-08)
**Plans**: 3/3 complete

Plans:
- [x] 02-01-PLAN.md — Pydantic extraction schemas, ExtractionService with Braintrust-wrapped OpenAI client, static system prompt with few-shot examples, tenacity retry, test scaffold
- [x] 02-02-PLAN.md — Alembic migration (PineconeSyncQueue table), JobRepository, WorkRequestRepository, Pinecone embedding write with fire-and-forget fallback, lifespan singleton
- [x] 02-03-PLAN.md — AuditLogRepository, raw GPT response storage, Inngest event integration tests


### Phase 02.10: be sure the temporal flows leverage distributed tracing via jaeger (INSERTED)

**Goal:** Wire Temporal's built-in OTel TracingInterceptor so that workflow and activity execution produces spans in Jaeger, with manual spans for sync_pinecone_queue_activity
**Requirements**: TRACING-01, TRACING-02, TRACING-03
**Depends on:** Phase 02.9
**Status**: Complete (2026-04-03)
**Plans:** 1/1 plans complete

Plans:
- [x] 02.10-01-PLAN.md — Wire TracingInterceptor on get_temporal_client, add manual span to sync_pinecone_queue_activity, add tests

### Phase 02.9: refactor the existing code to ensure temporal is being leveraged as opposed to inngest (INSERTED)

**Goal:** Replace all Inngest usage with Temporal so the app no longer depends on Inngest infrastructure. The observable behavior (SMS processing pipeline, Pinecone sync cron) must remain identical.
**Requirements**: TEMPORAL-01, TEMPORAL-02, TEMPORAL-03
**Depends on:** Phase 2
**Plans:** 1/1 plans complete

Plans:
- [ ] 02.9-01-PLAN.md — Create src/temporal/ package (activities, workflows, worker), update main/config/sms/docker-compose, migrate tests

### Phase 02.8: Review all existing code and refactor to CLAUDE.md standards (INSERTED)

**Goal:** Refactor all src/ files to meet FastAPI best practices defined in .claude/CLAUDE.md — Depends() injection for all SMS gates, UserRepository extraction, and EarlyReturn exception handler for Twilio 200-response paths. (Research confirmed Field() constraints, bug fix, inline imports, DB naming, and encapsulation are already done.)
**Requirements**: REFACTOR-01, REFACTOR-02, REFACTOR-03, REFACTOR-04, REFACTOR-05
**Depends on:** Phase 2
**Plans:** 2/2 plans complete

Plans:
- [x] 02.8-01-PLAN.md — SUPERSEDED by 02.8-02 (research found REFACTOR-03/04 already done in codebase)
- [x] 02.8-02-PLAN.md — UserRepository extraction, EarlyReturn exception handler, sms/router.py Depends() refactor

### Phase 02.8.1: refactor the code as appropriate taking SOLID principles into account (INSERTED)

**Goal:** Refactor PipelineOrchestrator.run() from 3 inline branches into Chain of Responsibility handler pattern, and extract duplicated session.add/flush/return across 4 repositories into BaseRepository Template Method — preparing the codebase for Phase 3/4 handler additions (OCP) and eliminating 4x persist duplication (DRY)
**Requirements**: SOLID-01, SOLID-02
**Depends on:** Phase 02.8
**Plans:** 1/1 plans complete

Plans:
- [ ] 02.8.1-PLAN.md — BaseRepository Template Method, Chain of Responsibility handlers, orchestrator refactor, DI rewiring

### Phase 02.7: flesh out the README.md to also include instructions for getting setup locally (INSERTED)

**Goal:** Write a complete README.md covering project purpose, local setup, environment variable reference, running tests, project structure, and deployment — so any developer can clone and run the stack without prior context
**Requirements**: DOC-README
**Depends on:** Phase 2
**Plans:** 1/1 plans complete

Plans:
- [ ] 02.7-01-PLAN.md — Write complete README.md (project overview, local setup, env vars, tests, structure, deployment)

### Phase 02.6: Ensure research docs are current (INSERTED)

**Goal:** Surgically update the 5 research docs in .planning/research/ (STACK.md, ARCHITECTURE.md, FEATURES.md, PITFALLS.md, SUMMARY.md) to reflect the actual implemented state after Phases 01-02.5, and add forward-looking sections for Phase 3/4 needs
**Requirements**: DOC-01, DOC-02, DOC-03
**Depends on:** Phase 02.5
**Plans:** 3/3 plans complete

Plans:
- [ ] 02.6-01-PLAN.md — Patch STACK.md and ARCHITECTURE.md (remove pgvector, add Inngest/Braintrust/Pinecone, update arch diagram and component names)
- [ ] 02.6-02-PLAN.md — Patch FEATURES.md and PITFALLS.md (annotate ✅/⏳, add Phase 3/4 sections, add implementation pitfalls 11-18)
- [ ] 02.6-03-PLAN.md — Comprehensive refresh of SUMMARY.md (replace all stale content with accurate built-system facts)

### Phase 02.1: Refactor persistence layer and service boundaries (INSERTED)

**Goal:** Clean architecture refactor — split ExtractionService into GPT-only service + PipelineOrchestrator, add MessageRepository/AuditLogRepository, normalize repositories to flush-only, group Settings into 4 nested Pydantic models, convert boolean returns to exceptions, wire full DI graph through FastAPI lifespan
**Requirements**: layering/DI, persistence/repositories, transactions/flush, config/settings, exception-handling
**Depends on:** Phase 2
**Status**: Complete (2026-03-08)
**Plans:** 3/3 complete

Plans:
- [x] 02.1-01-PLAN.md — Config nesting (4 sub-models), MessageRepository, AuditLogRepository, exception-based SMS router, Wave 0 test scaffold
- [x] 02.1-02-PLAN.md — ExtractionService decomposition (GPT-only), PipelineOrchestrator creation, flush-only repository normalization
- [x] 02.1-03-PLAN.md — Full DI graph in lifespan, Inngest function wiring to orchestrator, 3 integration happy-path tests

### Phase 02.3: Migrate Jaeger to v2 and optimize tracing setup (INSERTED)

**Goal:** Jaeger v1 all-in-one replaced with Jaeger v2 (collector + query) backed by OpenSearch 2.19.4; OTel TracerProvider configured with ALWAYS_ON sampler and extended resource attributes; manual spans added to all four uninstrumented pipeline steps (Inngest function, GPT, Pinecone, Twilio)
**Depends on:** Phase 2
**Status**: Complete (~2026-03-08)
**Plans:** 2/2 complete

Plans:
- [x] 02.3-01-PLAN.md — Jaeger v2 docker-compose migration (opensearch + jaeger-collector + jaeger-query), YAML config files, `_configure_otel()` ALWAYS_ON sampler + resource attributes
- [x] 02.3-02-PLAN.md — Manual OTel spans for Inngest function, GPT calls, Pinecone upserts, Twilio SMS; span attribute conventions; unit tests with InMemorySpanExporter

### Phase 02.4: Ensure Prometheus is setup (INSERTED)

**Goal:** Prometheus and Grafana added to Docker Compose with full auto-provisioning; custom GPT and queue-depth metrics instrumented in the application — zero manual setup after `docker compose up`
**Requirements**: OBS-02 (expanded)
**Depends on:** Phase 2
**Status**: Complete (~2026-03-08)
**Plans:** 2/2 complete

Plans:
- [x] 02.4-01-PLAN.md — `src/metrics.py` custom metric singletons, ExtractionService GPT instrumentation (token counters + latency histogram), pinecone_sync_queue_depth gauge background task, unit tests
- [x] 02.4-02-PLAN.md — Prometheus + Grafana Docker Compose services, config/provisioning files, pre-built FastAPI dashboard, human verification checkpoint

### Phase 02.5: Production hardening — staff-level readiness audit (INSERTED)

**Goal:** Bring the app from dev-complete to production-ready on Render.com — multi-stage Dockerfile, Inngest retry/failure handling, sync_pinecone_queue real implementation, render.yaml Blueprint IaC, GitHub Actions CI, and test coverage audit
**Requirements**: PROD-01 through PROD-08
**Depends on:** Phase 02.4
**Status**: Complete (2026-03-08)
**Plans:** 4/4 complete

Plans:
- [x] 02.5-01-PLAN.md — Dockerfile multi-stage hardening, pipeline_failures_total counter, gauge updater silent-failure fix, Inngest retry + on_failure wiring
- [x] 02.5-02-PLAN.md — sync_pinecone_queue real sweep implementation, openai_client injection from lifespan, unit tests
- [x] 02.5-03-PLAN.md — render.yaml Blueprint, .env.example completeness audit, GitHub Actions CI pipeline
- [x] 02.5-04-PLAN.md — pytest-cov install, coverage report, missing tests for Wave 1 critical paths

### Phase 3: Earnings Math Matching
**Goal**: A tested MatchService exists that accepts a worker goal record and returns a ranked list of jobs satisfying `rate × duration >= target_earnings`, sorted by soonest available then shortest duration, with SMS formatting and empty-match handling — ready to be called from the Inngest function in Phase 4
**Depends on**: Phase 02.5
**Requirements**: MATCH-01, MATCH-02, MATCH-03
**Success Criteria** (what must be TRUE):
  1. Given seeded job data, a worker goal query returns only jobs where `rate × estimated_duration >= target_earnings`, ordered by soonest available date then shortest duration
  2. The SMS formatter produces a condensed ranked list of 3-5 jobs that fits within 160-character segment boundaries
  3. When no jobs match the worker goal, the system produces a graceful "no matches" reply message rather than an empty response
**Status**: Not started
**Plans**: TBD

Plans:
- [ ] 03-01: MatchService + JobRepository earnings math SQL query with explicit NULL handling, Python-level sort, SMS formatter, empty-match fallback

### Phase 4: End-to-End Integration & Deployment
**Goal**: The full message pipeline runs end-to-end through the Inngest `process-message` function — from SMS receipt through GPT extraction, storage, matching, and outbound Twilio SMS reply — and the system is deployed to Render.com with STOP/START compliance verified
**Depends on**: Phase 3
**Requirements**: SEC-05, STR-03, ASYNC-02, DEP-03
**Success Criteria** (what must be TRUE):
  1. Texting a job posting results in a Twilio SMS confirmation to the poster summarizing extracted fields (pay, duration, location) within a reasonable time window after the webhook returns 200
  2. Texting a worker earnings goal results in a Twilio SMS reply containing a ranked list of matching jobs (or a graceful no-match message) without the webhook hanging
  3. Texting STOP or START results in the keyword being passed through to Twilio without the system attempting GPT classification or storage
  4. The Render.com deployment is live and reachable; Inngest Cloud functions are registered and processing events
**Status**: Not started
**Plans**: TBD

Plans:
- [ ] 04-01: Inngest `process-message` function fully wired (matching + SMS reply + poster confirmation + STOP/START pass-through)
- [ ] 04-02: Render.com production deploy, Inngest Cloud wiring, environment variable documentation, smoke test

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 01.1 → 2 → 02.1 → 02.3 → 02.4 → 02.5 → 3 → 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Infrastructure Foundation | 3/3 | Complete | 2026-03-06 |
| 01.1. Apply revised 3NF schema | 2/2 | Complete | 2026-03-07 |
| 2. GPT Extraction Service | 3/3 | Complete | ~2026-03-08 |
| 02.1. Refactor persistence layer | 3/3 | Complete | 2026-03-08 |
| 02.3. Migrate Jaeger to v2 | 2/2 | Complete | ~2026-03-08 |
| 02.4. Ensure Prometheus setup | 2/2 | Complete | ~2026-03-08 |
| 02.5. Production hardening | 4/4 | Complete | 2026-03-08 |
| 02.9. Inngest to Temporal migration | 0/1 | Complete    | 2026-04-03 |
| 3. Earnings Math Matching | 0/1 | Not started | — |
| 4. End-to-End Integration & Deployment | 0/2 | Not started | — |
