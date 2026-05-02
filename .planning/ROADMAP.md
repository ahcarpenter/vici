# Roadmap: Vici

## Overview

Vici is built in phases that follow a strict dependency order: infrastructure before domain logic, domain logic before integration, integration before deployment. Phase 1 lays the async foundation (DB, schema, security, observability, Temporal skeleton). The inserted decimal phases (01.1, 02.1, 02.3, 02.4, 02.5, 02.6, 02.7, 02.8, 02.8.1, 02.9, 02.10, 02.11, 02.12, 02.13, 02.13.1, 02.14) addressed schema normalization, architecture refactors, production hardening, documentation, Temporal migration, distributed tracing, edge-case hardening, and 3NF normalization before moving forward. Phase 3 adds deterministic earnings-math matching. Phase 4 wires all components end-to-end (deferred). Phases 5–9 are the v1.1 *De-platform* milestone: re-baseline the repo as a hosting-agnostic, Docker-only application — GHCR image distribution + CI compose validation (5), 3-file compose overlay with production hardening (6), Compose-native secrets via SOPS+age (7), Temporal Postgres visibility + observability container removal (8), and final GKE/GCP/Pulumi/Helm/ESO/Render cleanup (9, last by mandate).

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3, 4): v1.0 planned milestone work
- Decimal phases (1.1, 2.1, 2.3–2.14): v1.0 urgent insertions (marked INSERTED)
- Integer phases (5, 6, 7, 8, 9): v1.1 *De-platform* milestone — continues from v1.0's last phase number (no `--reset-phase-numbers`)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Infrastructure Foundation** - Async API skeleton, schema migrations, security gates, observability, and event wiring (completed 2026-03-06)
- [x] **Phase 01.1: Apply revised 3NF schema** - Normalize schema to User/Message/WorkGoal with integer FKs (completed 2026-03-07)
- [x] **Phase 2: GPT Extraction Service** - Single-call GPT classify+extract pipeline with Pydantic schemas, Pinecone write, and storage (completed ~2026-03-08)
- [x] **Phase 02.1: Refactor persistence layer and service boundaries** - Clean DI graph, PipelineOrchestrator, flush-only repositories (completed 2026-03-08)
- [x] **Phase 02.3: Migrate Jaeger to v2 and optimize tracing setup** - Jaeger v2 + OpenSearch, ALWAYS_ON sampler, manual spans (completed ~2026-03-08)
- [x] **Phase 02.4: Ensure Prometheus is setup** - Prometheus + Grafana in Docker Compose, custom GPT metrics, auto-provisioning (completed ~2026-03-08)
- [x] **Phase 02.5: Production hardening** - Multi-stage Dockerfile, Temporal retries, sync_pinecone_queue sweep, render.yaml, GitHub Actions CI, test coverage audit (completed 2026-03-08)
- [x] **Phase 02.6: Ensure research docs are current** - Update 5 research docs to reflect actual implemented state after Phases 01-02.5 (completed 2026-04-03)
- [x] **Phase 02.7: Flesh out the README.md** - Complete README with local setup, env vars, tests, structure, deployment (completed 2026-04-03)
- [x] **Phase 02.8: Refactor to CLAUDE.md standards** - UserRepository extraction, EarlyReturn exception handler, Depends() refactor (completed 2026-04-03)
- [x] **Phase 02.8.1: SOLID principles refactor** - Chain of Responsibility handler pattern, BaseRepository Template Method (completed 2026-04-03)
- [x] **Phase 02.9: Migrate from Inngest to Temporal** - Replace all Inngest usage with Temporal workflows and activities (completed 2026-04-03)
- [x] **Phase 02.10: Temporal distributed tracing** - Wire TracingInterceptor for Temporal workflow/activity spans in Jaeger (completed 2026-04-03)
- [x] **Phase 02.11: Edge-case hardening** - 13 edge-case fixes: config validation, GPT None guard, rate limit rolling window, graceful shutdown (completed 2026-04-03)
- [x] **Phase 02.12: Simplify architecture** - Distill app essence and map domains canonically (completed 2026-04-03)
- [x] **Phase 02.13: Refactor to AGENTS.md standards** - Fix DRY violations, rename files per domain conventions, extract SRP concerns (completed 2026-04-03)
- [x] **Phase 02.13.1: Distributed tracing gap coverage** - OTel span coverage for orchestrator, handlers, router, activities; PII fix; semconv fix (completed 2026-04-03)
- [x] **Phase 02.14: Normalize schema to 3NF** - Drop transitive user_id from Job/WorkGoal, fix rate_limit constraint, add audit_log check (completed 2026-04-03)
- [x] **Phase 3: Earnings Math Matching** - Deterministic SQL matching query, ranked SMS formatter, and empty-match handling (completed 2026-04-04)
- [ ] **Phase 4: End-to-End Integration & Deployment** - Temporal orchestration fully wired, outbound SMS replies, STOP/START compliance, and Render.com production deploy *(v1.0 — deferred)*

### v1.1 De-platform — Docker-Only Base

- [ ] **Phase 5: GHCR Image Distribution & CI Validation** - Multi-arch images to GHCR (SHA-tagged, no `:latest`); CI validates both compose overlays; legacy GKE CD workflows deleted
- [ ] **Phase 6: 3-File Compose Overlay & Production Hardening** - `docker-compose.yml` + `docker-compose.override.yml` (dev) + `docker-compose.prod.yml` (prod); healthchecks, restart policies, named volumes, resource limits, log rotation, `127.0.0.1:` bindings, `app-migrate` one-shot service; latent dev-compose bugs fixed
- [ ] **Phase 7: Compose-Native Secrets via SOPS + age** - Top-level `secrets:` block with file source for every credential; SOPS+age encryption at rest; pydantic Settings reads `/run/secrets/` via `secrets_dir=`; `grafana_admin_password = "admin"` literal removed
- [ ] **Phase 8: Temporal Postgres Visibility + Observability Container Removal** - `temporalio/auto-setup:1.31.0` with `ENABLE_ES=false`; three logical DBs in shared `postgres` service; OpenSearch + Prometheus + Grafana + Jaeger services removed; OTel console exporter as fallback; `/metrics` endpoint stays
- [ ] **Phase 9: GKE/GCP/Pulumi/Helm/ESO/Render Cleanup** - `infra/`, `helm/`, `k8s/`, ESO manifests, `render.yaml`, `Pulumi.*.yaml`, `.env.opensearch*` deleted; `gks-refactor` workstream archived; `pulumi destroy` runbook with hard-gate clean-exit before state deletion (last by mandate)

## Phase Details

### Phase 1: Infrastructure Foundation
**Goal**: A deployable, secure API skeleton exists with full observability, database schema, async session management, Twilio signature validation, idempotency, rate limiting, and event emission — so every subsequent phase builds on a correct, tested foundation
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

**Goal:** Replace Phone/InboundMessage/Worker with User/Message/WorkGoal using integer FKs; eliminate phone_hash string pseudo-FKs throughout the app
**Requirements**: IDN-01 (schema normalization), all repositories updated
**Depends on:** Phase 1
**Status**: Complete (2026-03-07)
**Plans:** 2/2 complete

Plans:
- [x] 01.1-01-PLAN.md — Alembic migration, User/Message/WorkGoal SQLModels, updated repositories
- [x] 01.1-02-PLAN.md — Propagate schema changes through all services, tests, and fixtures

### Phase 2: GPT Extraction Service
**Goal**: A tested ExtractionService exists that accepts raw SMS text and returns a validated `JobExtraction | WorkerExtraction | UnknownMessage` discriminated union, stores results in PostgreSQL, and writes job embeddings to Pinecone — so Phase 3 can query against real structured data
**Depends on**: Phase 01.1
**Requirements**: EXT-01, EXT-02, EXT-03, EXT-04, STR-01, STR-02, VEC-01, OBS-01
**Status**: Complete (~2026-03-08)
**Plans**: 3/3 complete

Plans:
- [x] 02-01-PLAN.md — Pydantic extraction schemas, ExtractionService with Braintrust-wrapped OpenAI client, static system prompt with few-shot examples, tenacity retry, test scaffold
- [x] 02-02-PLAN.md — Alembic migration (PineconeSyncQueue table), JobRepository, WorkGoalRepository, Pinecone embedding write with fire-and-forget fallback, lifespan singleton
- [x] 02-03-PLAN.md — AuditLogRepository, raw GPT response storage, Inngest event integration tests


### Phase 02.14: normalize database schema to third normal form (3NF) (INSERTED)

**Goal:** Normalize the database schema to strict 3NF by removing transitively-determined redundant user_id columns from job and work_goal, dropping the incompatible UNIQUE(user_id, created_at) constraint on rate_limit, and adding a CHECK constraint to enforce the audit_log message_sid invariant
**Requirements**: 3NF-01, 3NF-02, 3NF-03, 3NF-04, 3NF-05, 3NF-06
**Depends on:** Phase 2
**Plans:** 1/1 plans complete

Plans:
- [x] 02.14-01-PLAN.md — Drop job.user_id/work_goal.user_id, remove rate_limit unique constraint, add audit_log check; update models/schemas/repositories/handlers/tests

### Phase 02.13: ruthlessly refactor this codebase where appropriate in light of the latest revisions to AGENTS.md (INSERTED)

**Goal:** Apply SOLID and DRY relentlessly per updated AGENTS.md — fix GPT_MODEL DRY violation (ExtractionService bypasses injected settings), rename pinecone_client.py to utils.py (domain file naming), and extract _update_gauges from lifespan to module-level (SRP)
**Requirements**: DRY-01, DRY-02, SOLID-SRP-01, NAMING-01
**Depends on:** Phase 02.12
**Plans:** 1/1 plans complete

Plans:
- [x] 02.13-01-PLAN.md — Fix DRY in ExtractionService, rename pinecone_client.py to utils.py, extract _update_gauges to module level

### Phase 02.13.1: cover all distributed tracing gaps (INSERTED)

**Goal:** Close all OTel span coverage gaps so Jaeger shows complete, PII-safe request traces from Twilio webhook receipt through Temporal workflow completion — pipeline.orchestrate, pipeline.handle_worker_goal, enriched SMS router span, enriched activity span, PII fix in unknown handler, and semconv fix in job_posting handler
**Requirements**: TRACING-GAP-01, TRACING-GAP-02, TRACING-GAP-03, TRACING-GAP-04, TRACING-GAP-05, TRACING-GAP-06
**Depends on:** Phase 02.13
**Plans:** 1/1 plans complete

Plans:
- [x] 02.13.1-01-PLAN.md — OTel constants module, orchestrator/handler/router/activity span enrichment, PII fix, semconv fix, span assertion tests

### Phase 02.12: simplify architecture — distill app essence and map domains canonically (INSERTED)

**Goal:** Simplify the application architecture by distilling the app to its essential domains and mapping them canonically — ensuring domain boundaries, naming, and module structure reflect the actual system
**Requirements**: SIMPLIFY-01
**Depends on:** Phase 2
**Plans:** 1/1 plans complete

Plans:
- [x] 02.12-01-PLAN.md — Distill app essence, map domains canonically, simplify module structure

### Phase 02.11: you're a FAANG level distinguished engineer. For all existing features, find and account for all edge cases, ensuring they're handled gracefully (INSERTED)

**Goal:** Harden all existing features against 13 identified edge cases — fail-fast config validation, GPT None guard, correct Temporal error signaling, caught Twilio/Pinecone failures, rolling rate limit, graceful shutdown, webhook field validation, hash guard, datetime warning, and gauge staleness detection
**Requirements**: HARDENING-01
**Depends on:** Phase 02.10
**Plans:** 1/1 plans complete

Plans:
- [x] 02.11-01-PLAN.md — All 13 edge-case fixes across config, extraction, activities, handlers, sms, jobs, and main

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
- [x] 02.9-01-PLAN.md — Create src/temporal/ package (activities, workflows, worker), update main/config/sms/docker-compose, migrate tests

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
- [x] 02.8.1-PLAN.md — BaseRepository Template Method, Chain of Responsibility handlers, orchestrator refactor, DI rewiring

### Phase 02.7: flesh out the README.md to also include instructions for getting setup locally (INSERTED)

**Goal:** Write a complete README.md covering project purpose, local setup, environment variable reference, running tests, project structure, and deployment — so any developer can clone and run the stack without prior context
**Requirements**: DOC-README
**Depends on:** Phase 2
**Plans:** 1/1 plans complete

Plans:
- [x] 02.7-01-PLAN.md — Write complete README.md (project overview, local setup, env vars, tests, structure, deployment)

### Phase 02.6: Ensure research docs are current (INSERTED)

**Goal:** Surgically update the 5 research docs in .planning/research/ (STACK.md, ARCHITECTURE.md, FEATURES.md, PITFALLS.md, SUMMARY.md) to reflect the actual implemented state after Phases 01-02.5, and add forward-looking sections for Phase 3/4 needs
**Requirements**: DOC-01, DOC-02, DOC-03
**Depends on:** Phase 02.5
**Plans:** 3/3 plans complete

Plans:
- [x] 02.6-01-PLAN.md — Patch STACK.md and ARCHITECTURE.md (remove pgvector, add Temporal/Braintrust/Pinecone, update arch diagram and component names)
- [x] 02.6-02-PLAN.md — Patch FEATURES.md and PITFALLS.md (annotate status, add Phase 3/4 sections, add implementation pitfalls 05-18)
- [x] 02.6-03-PLAN.md — Comprehensive refresh of SUMMARY.md (replace all stale content with accurate built-system facts)

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
**Goal**: A tested MatchService exists that accepts a worker goal record and returns a ranked list of jobs satisfying `rate × duration >= target_earnings`, sorted by soonest available then shortest duration, with SMS formatting and empty-match handling — ready to be called from the Temporal workflow in Phase 4
**Depends on**: Phase 02.5
**Requirements**: MATCH-01, MATCH-02, MATCH-03
**Success Criteria** (what must be TRUE):
  1. Given seeded job data, a worker goal query returns only jobs where `rate × estimated_duration >= target_earnings`, ordered by soonest available date then shortest duration
  2. The SMS formatter produces a condensed ranked list of 3-5 jobs that fits within 160-character segment boundaries
  3. When no jobs match the worker goal, the system produces a graceful "no matches" reply message rather than an empty response
**Status**: Complete (2026-04-04)
**Plans**: 1 plan

Plans:
- [x] 03-01-PLAN.md — phone_e164 migration, job.status migration, DP MatchService, SMS formatter, MatchRepository, full test suite

### Phase 4: End-to-End Integration & Deployment
**Goal**: The full message pipeline runs end-to-end through the Temporal `ProcessMessageWorkflow` — from SMS receipt through GPT extraction, storage, matching, and outbound Twilio SMS reply — and the system is deployed to Render.com with STOP/START compliance verified
**Depends on**: Phase 3
**Requirements**: SEC-05, STR-03, ASYNC-02, DEP-03
**Success Criteria** (what must be TRUE):
  1. Texting a job posting results in a Twilio SMS confirmation to the poster summarizing extracted fields (pay, duration, location) within a reasonable time window after the webhook returns 200
  2. Texting a worker earnings goal results in a Twilio SMS reply containing a ranked list of matching jobs (or a graceful no-match message) without the webhook hanging
  3. Texting STOP or START results in the keyword being passed through to Twilio without the system attempting GPT classification or storage
  4. The Render.com deployment is live and reachable; Temporal workflows are registered and processing events
**Status**: Not started
**Plans**: 1 plan

Plans:
- [ ] 04-01: Temporal `ProcessMessageWorkflow` fully wired (matching + SMS reply + poster confirmation + STOP/START pass-through)
- [ ] 04-02: Render.com production deploy, Temporal Cloud wiring, environment variable documentation, smoke test

---

## v1.1 De-platform — Docker-Only Base

### Phase 5: GHCR Image Distribution & CI Validation
**Goal**: Multi-arch Docker images published to GHCR with SHA-pinned tags on every `main` push and tag, and CI validates both compose overlays before merge — so subsequent phases can reference an immutable `image:` in `docker-compose.prod.yml` without ever building on a deploy host
**Depends on**: Nothing (independent of compose split; unblocks `image:` references for Phase 6)
**Requirements**: CI-01, CI-02, CI-03, CI-04
**Success Criteria** (what must be TRUE):
  1. A push to `main` triggers a GitHub Actions workflow that builds linux/amd64 + linux/arm64 images via QEMU + buildx and pushes them to `ghcr.io/<org>/vici:sha-<short>` (no `:latest` tag)
  2. The published image is pullable by an unauthenticated CI job and reports both architectures in `docker manifest inspect`
  3. Every push runs `docker compose -f docker-compose.yml config --quiet` AND `docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet`; either failing returns a non-zero exit and blocks the merge
  4. The legacy GKE-targeted CD workflows (`cd-base.yml`, `cd-dev.yml`, `cd-staging.yml`, `cd-prod.yml`) no longer run on push (deleted as part of CI-04, completed by Phase 9 INFRA-01 — but the workflow files are removed in this phase as the CI surface is reauthored)
**Plans:** 4 plans

Plans:
- [ ] 05-01-PLAN.md — Create `docker-compose.prod.yml` image-only stub (D-02) and verify locally that both compose-config invocations behave per D-03/D-04
- [ ] 05-02-PLAN.md — Delete the four legacy GKE-targeted CD workflow files (`cd-base.yml`, `cd-dev.yml`, `cd-staging.yml`, `cd-prod.yml`); D-17 satisfied transitively
- [ ] 05-03-PLAN.md — Extend `.github/workflows/ci.yml` with 5 new jobs: `compose-validate`, `build` (matrix amd64/arm64 native runners), `merge`, `verify` (anonymous, with corrected attestation predicate)
- [ ] 05-04-PLAN.md — Document D-08 (GHCR public-toggle) and D-18 (branch-protection update) operator runbook in README.md and pause for operator confirmation (autonomous: false)

### Phase 6: 3-File Compose Overlay & Production Hardening
**Goal**: The compose stack is split into a 3-file overlay (`docker-compose.yml` base + `docker-compose.override.yml` dev + `docker-compose.prod.yml` prod via explicit `-f`); the production overlay is operationally hardened (healthchecks, restart policies, named volumes, resource limits, log rotation, localhost-only port bindings) and the two latent dev-compose bugs (missing `postgres_data` named volume, `0.0.0.0` port bindings on internal services) are fixed in the same pass
**Depends on**: Phase 5 (so the prod overlay can reference `image: ghcr.io/<org>/vici:sha-${GIT_SHA}` from the start)
**Requirements**: COMPOSE-01, COMPOSE-02, COMPOSE-03, COMPOSE-04, COMPOSE-05, COMPOSE-06
**Success Criteria** (what must be TRUE):
  1. `docker compose up` (no flags) starts the dev stack with hot-reload via `docker-compose.override.yml` auto-loaded; `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d` starts the production stack with no source bind mounts and no `--reload`
  2. After `docker compose down && docker compose up`, the `postgres` service retains all data (verified by writing a row, restarting, and reading it back) — the `postgres_data` named volume is present in `docker volume ls`
  3. The production overlay binds every non-public service port to `127.0.0.1:` (verified via `nmap` from off-host showing only the app's HTTP listener); every long-running service has `restart: unless-stopped`, a healthcheck, `depends_on: { condition: service_healthy }` for upstream gates, a named volume for stateful paths, a pinned image (digest or SHA-tagged GHCR ref), `deploy.resources.limits` plus `mem_limit`/`cpus`, and JSON-file logging with `max-size`/`max-file` rotation
  4. The app's database migrations run as a one-shot `app-migrate` service that exits cleanly; the long-running `app` service starts only after `app-migrate` reports `service_completed_successfully` (no inline `alembic upgrade head` in the app's `command:`)
**Plans**: TBD

### Phase 7: Compose-Native Secrets via SOPS + age
**Goal**: All sensitive credentials in production are sourced from Compose-native `secrets:` (file source) mounted at `/run/secrets/`; the source files are encrypted at rest in the repo via SOPS + age and decrypted at deploy time via a documented operator command; pydantic Settings reads them via `secrets_dir=` while preserving the existing flat-env path for local dev; the obsolete `grafana_admin_password = "admin"` literal default is removed from `src/config.py`
**Depends on**: Phase 6 (production overlay must exist before secrets can be mounted into it)
**Requirements**: SECRETS-01, SECRETS-02, SECRETS-03, SECRETS-04
**Success Criteria** (what must be TRUE):
  1. The production overlay declares a top-level `secrets:` block that file-sources every sensitive credential (DB password, OpenAI key, Pinecone key, Twilio account SID + auth token, Twilio request validation token, Braintrust API key); each consuming service references them via `secrets:` and reads them through `/run/secrets/<name>`
  2. The Settings class reads secret values via `secrets_dir="/run/secrets"` when files are present and falls back to flat `.env` values when they are not; both paths are exercised by tests
  3. An operator can run a documented one-line command (e.g. `make decrypt-secrets`) that reads SOPS-encrypted files from `secrets/encrypted/`, decrypts them with an `SOPS_AGE_KEY_FILE` outside the repo, and writes plaintext files to `secrets/decrypted/` (gitignored, mode 0400) ready for `docker compose up -d`
  4. `rg -n 'grafana_admin_password.*=.*"admin"' src/` returns zero hits; any other secret defaults that are unsafe to ship are removed from `src/config.py`
**Plans**: TBD

### Phase 8: Temporal Postgres Visibility + Observability Container Removal
**Goal**: Temporal stays self-hosted in compose (no Cloud) but switches to Postgres-only advanced visibility — auto-setup is bumped to `temporalio/auto-setup:1.31.0` with `ENABLE_ES=false`, `VISIBILITY_DBNAME=temporal_visibility`, `DB=postgres12`, and Temporal's three logical databases (`temporal`, `temporal_visibility`, `vici`) live in the single shared `postgres` service via init scripts; OpenSearch, Prometheus, Grafana, and Jaeger services are removed from `docker-compose.yml` entirely; the app's OTel exporter defaults to a console (stdout) span exporter when `OTEL_EXPORTER_OTLP_ENDPOINT` is unset and uses OTLP when it is set; obsolete config files (Grafana provisioning, Prometheus rules, Jaeger collector configs) are deleted alongside the services
**Depends on**: Phase 6 (compose overlay split must exist before reshaping services)
**Requirements**: TEMPORAL-01, TEMPORAL-02, TEMPORAL-03, TEMPORAL-04, OBS-05, OBS-06, OBS-07, OBS-08, OBS-09
**Success Criteria** (what must be TRUE):
  1. `docker compose up` starts a stack containing Postgres, the app, the one-shot migrate service, and `temporalio/auto-setup:1.31.0` — no `opensearch`, `prometheus`, `grafana`, or `jaeger` services are present in `docker-compose.yml` or any overlay; obsolete config directories (Grafana provisioning, Prometheus rules, Jaeger collector configs) are deleted from the repo
  2. The Temporal server boots cleanly against Postgres-only visibility (`ENABLE_ES=false`, `VISIBILITY_DBNAME=temporal_visibility`, `DB=postgres12`); a workflow can be started, queried via `temporal workflow list`, and its history viewed without OpenSearch present
  3. The shared `postgres` service hosts three logical databases (`vici`, `temporal`, `temporal_visibility`) provisioned via init scripts on first boot; no second Postgres instance exists in any compose file
  4. `docker compose logs app` shows OTel spans printed via the console (stdout) span exporter when `OTEL_EXPORTER_OTLP_ENDPOINT` is unset; setting `OTEL_EXPORTER_OTLP_ENDPOINT` switches the app to the OTLP exporter without code changes; structlog continues to emit JSON logs to stdout for every inbound message and outbound reply
  5. The app's `/metrics` Prometheus endpoint stays exposed and returns valid metrics for any external scraper an operator wires up; the app does not require Prometheus, Grafana, or Jaeger to be present at runtime
**Plans**: TBD

### Phase 9: GKE/GCP/Pulumi/Helm/ESO/Render Cleanup
**Goal**: Every artifact tied to the abandoned platforms is removed from the repo (`infra/` Pulumi project, `helm/`, `k8s/`, External Secrets Operator manifests, `render.yaml`, `Pulumi.*.yaml`, the `cd-*.yml` workflows already deleted in Phase 5, `.env.opensearch*`); the `gks-refactor` workstream artifacts are archived to `.planning/milestones/v1.0-gks-refactor/`; a documented runbook captures the GCP teardown sequence (state export → `pulumi destroy` clean exit on every stack → GCP billing audit → only then delete Pulumi state files); a final repo-wide grep returns clean — no orphan references to the abandoned platforms anywhere in code, compose files, env templates, scripts, or docs
**Depends on**: Phase 8 (the new Docker-only baseline must be verified working end-to-end before deleting the only fallback)
**Requirements**: INFRA-01, INFRA-02, INFRA-03, INFRA-04
**Success Criteria** (what must be TRUE):
  1. A documented runbook (`docs/RUNBOOK-gcp-teardown.md` or equivalent) describes the destruction sequence and is executed end-to-end: `pulumi stack export > backup-state.json` for every stack → `pulumi destroy` returns clean exit code on every stack → GCP console + billing audit confirm zero recurring charges → only then are Pulumi state files deleted (this is a hard gate — no state deletion before clean-exit destroy)
  2. The repo no longer contains `infra/`, `helm/`, `k8s/`, External Secrets Operator manifests, `render.yaml`, `Pulumi.*.yaml`, or `.env.opensearch*` files; `git ls-files` confirms their absence
  3. `rg -i 'gke|gcp|helm|pulumi|cloud_sql|external-secret|render\.yaml'` against the working tree (excluding `.planning/milestones/` historical archives) returns zero hits in code, compose files, env templates, scripts, README, or AGENTS.md
  4. The `gks-refactor` workstream artifacts are moved from `.planning/workstreams/gks-refactor/` to `.planning/milestones/v1.0-gks-refactor/`; the active workstream pointer no longer references `gks-refactor`
**Plans**: TBD

## Progress

**Execution Order:**
1 → 01.1 → 2 → 02.1 → 02.3 → 02.4 → 02.5 → 02.6 → 02.7 → 02.8 → 02.8.1 → 02.9 → 02.10 → 02.11 → 02.12 → 02.13 → 02.13.1 → 02.14 → 3 → 4 *(v1.0 deferred)* → **5 → 6 → 7 → 8 → 9** *(v1.1 De-platform)*

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Infrastructure Foundation | 3/3 | Complete | 2026-03-06 |
| 01.1. Apply revised 3NF schema | 2/2 | Complete | 2026-03-07 |
| 2. GPT Extraction Service | 3/3 | Complete | ~2026-03-08 |
| 02.1. Refactor persistence layer | 3/3 | Complete | 2026-03-08 |
| 02.3. Migrate Jaeger to v2 | 2/2 | Complete | ~2026-03-08 |
| 02.4. Ensure Prometheus setup | 2/2 | Complete | ~2026-03-08 |
| 02.5. Production hardening | 4/4 | Complete | 2026-03-08 |
| 02.6. Ensure research docs current | 3/3 | Complete | 2026-04-03 |
| 02.7. Flesh out README.md | 1/1 | Complete | 2026-04-03 |
| 02.8. Refactor to CLAUDE.md standards | 2/2 | Complete | 2026-04-03 |
| 02.8.1. SOLID principles refactor | 1/1 | Complete | 2026-04-03 |
| 02.9. Inngest to Temporal migration | 1/1 | Complete | 2026-04-03 |
| 02.10. Temporal distributed tracing | 1/1 | Complete | 2026-04-03 |
| 02.11. Edge-case hardening | 1/1 | Complete | 2026-04-03 |
| 02.12. Simplify architecture | 1/1 | Complete | 2026-04-03 |
| 02.13. Refactor to AGENTS.md standards | 1/1 | Complete | 2026-04-03 |
| 02.13.1. Distributed tracing gaps | 1/1 | Complete | 2026-04-03 |
| 02.14. Normalize schema to 3NF | 1/1 | Complete | 2026-04-03 |
| 3. Earnings Math Matching | 1/1 | Complete   | 2026-04-05 |
| 4. End-to-End Integration & Deployment | 0/2 | Deferred (v1.0) | -- |
| 5. GHCR Image Distribution & CI Validation | 0/4 | Not started | -- |
| 6. 3-File Compose Overlay & Production Hardening | 0/0 | Not started | -- |
| 7. Compose-Native Secrets via SOPS + age | 0/0 | Not started | -- |
| 8. Temporal Postgres Visibility + Observability Removal | 0/0 | Not started | -- |
| 9. GKE/GCP/Pulumi/Helm/ESO/Render Cleanup | 0/0 | Not started | -- |

## Backlog

### Phase 999.1: Concerns Remediation — close outstanding items from 2026-04-22 codebase audit (BACKLOG)

**Goal:** Resolve the 14 unhandled concerns from `.planning/codebase/CONCERNS.md` (2026-04-22) that were classified manual-only or partial during the audit-fix pass. The auto-fixable subset (F-01…F-08, F-10…F-14, F-16…F-25, 17 items) is already merged on `main`; this backlog captures the residual architectural and cross-cutting work.
**Requirements:** TBD — discuss before planning. Spans security (HMAC phone hash, /metrics auth), correctness (transaction ownership, rate-limit TOCTOU, `phone_e164` backfill, pinecone sync same-txn update, Pinecone client reuse), reliability (Temporal emission orphan rows, rate_limit TTL), feature wiring (MatchService → SMS), tech debt (raw_sms persistence decision, temporal_queue_depth stub, sms/repository.py TODO), and dep hygiene (upgrade CVE-flagged transitives + tighten pip-audit to hard-fail).
**Plans:** 0 plans

Scope (condensed — see `.planning/codebase/CONCERNS.md` and audit-fix follow-ups):
- F-09 — `process_message_activity` transaction ownership refactor (remove per-handler `session.commit()`, wrap in `session.begin()`)
- F-11 follow-up — same-txn UPDATE for pinecone sync (`in_progress` status migration OR single-row batch)
- F-15 — hoist `PineconeAsyncio` context out of per-row loop + update 6 tests
- F-25 follow-up — upgrade aiohttp/requests/pyjwt/python-multipart/pygments/pytest; tighten `pip-audit` to hard-fail
- Unsalted SHA-256 phone hash → HMAC-SHA256 with `PHONE_HASH_SECRET` + backfill migration
- `/metrics` public exposure → internal port or K8s NetworkPolicy
- `phone_e164` not populated from SMS inbound (`UserRepository.get_or_create` + `ON CONFLICT` backfill)
- Rate-limit TOCTOU restructure (COUNT first, INSERT only if within limit)
- Temporal emission orphan messages (retry table + cron-drained activity)
- `rate_limit` table TTL pruning (scheduled Temporal activity)
- `JobCreate.raw_sms` decision (add columns vs. remove field)
- `MatchService` end-to-end wiring in `WorkerGoalHandler` + match metrics
- `temporal_queue_depth` stub — implement via Temporal SDK or remove
- `src/sms/repository.py:29-31` TODO removal (paired with rate-limit restructure)

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)
