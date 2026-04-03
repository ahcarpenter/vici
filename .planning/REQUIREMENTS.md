# Vici — v1 Requirements

**Milestone:** v1.0
**Generated:** 2026-03-05
**Last updated:** 2026-03-08 (post Phase 02.5)
**Status:** Active — Phases 01–02.5 complete; Phase 03 next

---

## v1 Requirements

### Security & Infrastructure (SEC)

- [x] **SEC-01**: System validates Twilio X-Twilio-Signature HMAC on every inbound webhook request and returns HTTP 403 on failure
- [x] **SEC-02**: System deduplicates inbound messages on MessageSid before any processing (unique constraint + idempotency check prevents duplicate job postings from Twilio retries)
- [x] **SEC-03**: System enforces per-phone-number rate limiting on inbound messages to prevent GPT/Twilio cost blowout from abuse or message loops
- [x] **SEC-04**: System stores the raw SMS body and raw GPT response in an audit table for every inbound message, regardless of classification outcome
- [ ] **SEC-05**: System passes STOP and START keywords through to Twilio without processing (carrier-level compliance)

### Identity (IDN)

- [x] **IDN-01**: System auto-registers a phone number as a user identity on first inbound message using E.164-normalized number as the primary key (no signup, no auth)
- [x] **IDN-02**: System records created_at timestamp for each phone number identity to support number recycling detection

### Message Classification & Extraction (EXT)

- [x] **EXT-01**: System classifies each inbound SMS as a job posting, worker earnings goal, or unknown using a single GPT call
- [x] **EXT-02**: System extracts the following fields from a job posting message: job description, ideal date/time, date/time flexibility, estimated duration (optional), location, and pay/rate
- [x] **EXT-03**: System extracts the following fields from a worker goal message: target earnings amount and target timeframe
- [x] **EXT-04**: System sends a graceful SMS reply to the sender when a message cannot be classified, prompting them to try again

### Storage (STR)

- [x] **STR-01**: System stores extracted job postings as structured records in PostgreSQL (job ID used as Pinecone vector key; no embedding column in PostgreSQL)
- [x] **STR-02**: System stores extracted worker goals as structured records in PostgreSQL
- [ ] **STR-03**: System sends a confirmation SMS to the job poster summarizing the extracted fields (e.g., "Got it: $25/hr, 3 hrs, downtown — reply EDIT to correct")

### Vector Search (VEC)

- [x] **VEC-01**: System integrates Pinecone as the vector store; job embeddings are written to Pinecone at job creation time using `text-embedding-3-small` (1536 dims); failed writes are queued in `pinecone_sync_queue` and retried by a cron Inngest function

### Job Matching (MATCH)

- [ ] **MATCH-01**: System computes job matches for a worker goal using earnings math: rate × estimated_duration ≥ target_earnings, results sorted by soonest available date then shortest duration
- [ ] **MATCH-02**: System sends a ranked list of 3–5 matching jobs to the worker via SMS in a condensed format that respects 160-character segment boundaries
- [ ] **MATCH-03**: System sends a graceful SMS reply to the worker when no jobs match their goal

### Observability (OBS)

- [x] **OBS-01**: System instruments all GPT classify+extract calls with Braintrust LLM observability (input prompt, output, model, latency, token usage per call)
- [x] **OBS-02**: System exposes a Prometheus-compatible `/metrics` endpoint with request count, latency histograms, error rates, and GPT call metrics; Prometheus + Grafana run in Docker Compose with auto-provisioning and a pre-built FastAPI dashboard
- [x] **OBS-03**: System instruments all inbound and outbound HTTP requests, database queries, and Inngest function executions with OpenTelemetry traces (ALWAYS_ON sampler, OTLP gRPC export to Jaeger v2 collector backed by OpenSearch); manual spans added to Inngest function, GPT calls, Pinecone upserts, and Twilio SMS
- [x] **OBS-04**: System emits structured JSON logs with per-request context (phone hash, message_id, trace_id) on every inbound message and outbound reply

### Async Processing (ASYNC)

- [x] **ASYNC-01**: Webhook route fires an Inngest event (`message.received`) immediately after validating the Twilio signature and MessageSid idempotency check, then returns HTTP 200 to Twilio — all GPT processing happens outside the Twilio response window
- [ ] **ASYNC-02**: Inngest function `process-message` handles the full pipeline: GPT classify+extract → PostgreSQL storage → Pinecone embedding write → earnings math match → Twilio REST SMS reply *(GPT + storage + Pinecone complete; matching + outbound SMS reply pending Phase 3/4)*
- [x] **ASYNC-03**: Inngest is configured for local development via the Inngest Dev Server (runs in Docker Compose); production uses Inngest Cloud (INNGEST_SIGNING_KEY + INNGEST_EVENT_KEY)

### Deployment (DEP)

- [x] **DEP-01**: System runs locally via Docker Compose (8 services: postgres, opensearch, jaeger-collector, jaeger-query, app, inngest, prometheus, grafana)
- [x] **DEP-02**: System exposes a `/health` endpoint returning service status, suitable for platform health checks (liveness only; no DB dependency)
- [ ] **DEP-03**: System is deployable to Render.com via `render.yaml` Blueprint; web service + PostgreSQL provisioned via IaC; pre-deploy migration hook runs `alembic upgrade head` *(render.yaml exists and is complete; pending first production deploy validation)*

### Production Hardening (PROD)

- [x] **PROD-01**: Multi-stage Dockerfile — builder stage (uv sync, frozen deps) + runtime stage (non-root appuser, curl for HEALTHCHECK, no dev dependencies)
- [x] **PROD-02**: Inngest `process-message` function configured with 3 retries and an `on_failure` handler that increments `pipeline_failures_total` Prometheus counter and logs permanent failures via structlog
- [x] **PROD-03**: `sync-pinecone-queue` Inngest cron sweeps `pinecone_sync_queue` for pending rows (max 50/run), calls `write_job_embedding()`, marks rows success/failed with retry_count increment
- [x] **PROD-04**: `render.yaml` Blueprint defines vici web service (Docker runtime, Oregon, starter plan) and vici-db PostgreSQL 16 (basic-256mb) with all required environment variable definitions
- [x] **PROD-05**: GitHub Actions CI pipeline runs pytest with SQLite+aiosqlite on every push; pytest-cov reports coverage
- [x] **PROD-06**: `.env.example` is complete and documents all required environment variables
- [x] **PROD-07**: Gauge updater background task polls `pinecone_sync_queue` every 15 seconds; silent failures logged as warnings (does not crash app)
- [x] **PROD-08**: Test coverage audit complete for Wave 1 critical paths (webhook → extraction → storage)

---

## v2 Requirements (Deferred)

- Semantic job matching via Pinecone vector search (embeddings written in v1, query logic deferred)
- Additional Inngest functions for scheduled jobs or multi-step workflows (v1 uses a single process-message function)
- Web dashboard or admin UI
- Multi-turn conversation state / dialog management
- Field-level extraction confidence with clarification prompts
- SMS query commands ("MY JOBS", "CANCEL JOB 2") for poster management
- Time-of-send context inference for relative datetime expressions ("tomorrow morning")

---

## Out of Scope (v1)

- User registration or auth flows — phone number is identity; first text auto-registers
- Web UI or dashboard — API only for MVP
- Multiple Twilio phone numbers or routing logic — single inbound number
- Real-time push notifications — SMS reply is the only notification mechanism
- Payment processing — rate/pay is informational only in v1
- Semantic/Pinecone vector matching — Pinecone integration ships in v1 (embedding writes); vector search query deferred to v2
- Redis — rate limiting uses PostgreSQL TTL counters to avoid infrastructure dependency at v1 scale
- pgvector — Pinecone is the vector store; postgres:16 plain image used

---

## Requirement Traceability

| REQ-ID | Phase | Status | Notes |
|--------|-------|--------|-------|
| SEC-01 | Phase 1 | Complete | Signature validation is a security gate; must be first |
| SEC-02 | Phase 1 | Complete | Idempotency before any processing — cheap to add early, expensive to retrofit |
| SEC-03 | Phase 1 | Complete | Rate limiting before GPT calls to prevent cost blowout |
| SEC-04 | Phase 1 | Complete | Audit table in initial migration; raw GPT response column populated in Phase 2 |
| SEC-05 | Phase 4 | Pending | STOP/START pass-through wired in Inngest process-message function |
| IDN-01 | Phase 1 | Complete | Phone identity auto-registration in initial schema |
| IDN-02 | Phase 1 | Complete | created_at in initial schema for recycling detection |
| EXT-01 | Phase 2 | Complete | gpt-5.3-chat-latest classify+extract via beta.chat.completions.parse in ExtractionService |
| EXT-02 | Phase 2 | Complete | JobExtraction Pydantic schema + structured output prompt |
| EXT-03 | Phase 2 | Complete | WorkerExtraction Pydantic schema + structured output prompt |
| EXT-04 | Phase 2 | Complete | UnknownMessage branch — Twilio reply sent in PipelineOrchestrator |
| STR-01 | Phase 2 | Complete | JobRepository.create() flush; PipelineOrchestrator commits per branch |
| STR-02 | Phase 2 | Complete | WorkGoalRepository.create() flush; PipelineOrchestrator commits per branch |
| STR-03 | Phase 4 | Pending | Confirmation SMS wired in Inngest process-message function |
| VEC-01 | Phase 2 | Complete | write_job_embedding() in pinecone_client.py; failure fallback to pinecone_sync_queue |
| MATCH-01 | Phase 3 | Pending | Earnings math SQL query in JobRepository |
| MATCH-02 | Phase 3 | Pending | Ranked SMS formatter (3-5 results, 160-char segments) |
| MATCH-03 | Phase 3 | Pending | Empty match fallback reply |
| OBS-01 | Phase 2 | Complete | Braintrust wraps GPT calls in ExtractionService; token metrics recorded |
| OBS-02 | Phase 1/02.4 | Complete | Prometheus /metrics endpoint + Grafana auto-provisioning in Docker Compose |
| OBS-03 | Phase 1/02.3 | Complete | OTel ALWAYS_ON; Jaeger v2 + OpenSearch; manual spans in all 4 pipeline steps |
| OBS-04 | Phase 1 | Complete | structlog JSON with per-request context (phone hash, message_id, trace_id) |
| ASYNC-01 | Phase 1 | Complete | Inngest event emit; returns 200 before any GPT work |
| ASYNC-02 | Phase 4 | Partial | GPT + storage + Pinecone complete; matching + SMS reply pending |
| ASYNC-03 | Phase 1 | Complete | Inngest Dev Server in Docker Compose; Inngest Cloud config documented |
| DEP-01 | Phase 1 | Complete | Docker Compose with 8 services (postgres, opensearch, jaeger×2, app, inngest, prometheus, grafana) |
| DEP-02 | Phase 1 | Complete | /health endpoint (liveness only, no DB dependency) |
| DEP-03 | Phase 02.5 | Complete | render.yaml Blueprint shipped; production deploy pending first run |
| PROD-01 | Phase 02.5 | Complete | Multi-stage Dockerfile |
| PROD-02 | Phase 02.5 | Complete | Inngest retries + on_failure handler |
| PROD-03 | Phase 02.5 | Complete | sync-pinecone-queue sweep implementation |
| PROD-04 | Phase 02.5 | Complete | render.yaml Blueprint |
| PROD-05 | Phase 02.5 | Complete | GitHub Actions CI |
| PROD-06 | Phase 02.5 | Complete | .env.example audit |
| PROD-07 | Phase 02.5 | Complete | Gauge updater background task |
| PROD-08 | Phase 02.5 | Complete | Wave 1 coverage audit |
| DOC-README | Phase 02.7 | Complete | Full developer README with local setup, env vars, architecture, and deployment |
