# Vici — v1 Requirements

**Milestone:** v1.0
**Generated:** 2026-03-05
**Status:** Active

---

## v1 Requirements

### Security & Infrastructure (SEC)

- [ ] **SEC-01**: System validates Twilio X-Twilio-Signature HMAC on every inbound webhook request and returns HTTP 403 on failure
- [ ] **SEC-02**: System deduplicates inbound messages on MessageSid before any processing (unique constraint + idempotency check prevents duplicate job postings from Twilio retries)
- [ ] **SEC-03**: System enforces per-phone-number rate limiting on inbound messages to prevent GPT/Twilio cost blowout from abuse or message loops
- [ ] **SEC-04**: System stores the raw SMS body and raw GPT response in an audit table for every inbound message, regardless of classification outcome
- [ ] **SEC-05**: System passes STOP and START keywords through to Twilio without processing (carrier-level compliance)

### Identity (IDN)

- [ ] **IDN-01**: System auto-registers a phone number as a user identity on first inbound message using E.164-normalized number as the primary key (no signup, no auth)
- [ ] **IDN-02**: System records created_at timestamp for each phone number identity to support number recycling detection

### Message Classification & Extraction (EXT)

- [ ] **EXT-01**: System classifies each inbound SMS as a job posting, worker earnings goal, or unknown using a single GPT call
- [ ] **EXT-02**: System extracts the following fields from a job posting message: job description, ideal date/time, date/time flexibility, estimated duration (optional), location, and pay/rate
- [ ] **EXT-03**: System extracts the following fields from a worker goal message: target earnings amount and target timeframe
- [ ] **EXT-04**: System sends a graceful SMS reply to the sender when a message cannot be classified, prompting them to try again

### Storage (STR)

- [ ] **STR-01**: System stores extracted job postings as structured records in PostgreSQL, with a nullable embedding column reserved for future Pinecone-backed semantic matching
- [ ] **STR-02**: System stores extracted worker goals as structured records in PostgreSQL
- [ ] **STR-03**: System sends a confirmation SMS to the job poster summarizing the extracted fields (e.g., "Got it: $25/hr, 3 hrs, downtown — reply EDIT to correct")

### Vector Search (VEC)

- [ ] **VEC-01**: System integrates Pinecone as the vector store; job embeddings are written to Pinecone at job creation time (v1 stores embeddings; semantic matching query is deferred to v2)

### Job Matching (MATCH)

- [ ] **MATCH-01**: System computes job matches for a worker goal using earnings math: rate × estimated_duration ≥ target_earnings, results sorted by soonest available date then shortest duration
- [ ] **MATCH-02**: System sends a ranked list of 3–5 matching jobs to the worker via SMS in a condensed format that respects 160-character segment boundaries
- [ ] **MATCH-03**: System sends a graceful SMS reply to the worker when no jobs match their goal

### Observability (OBS)

- [ ] **OBS-01**: System instruments all GPT classify+extract calls with Braintrust LLM observability (input prompt, output, model, latency, token usage per call)
- [ ] **OBS-02**: System exposes a Prometheus-compatible `/metrics` endpoint with request count, latency histograms, error rates, and GPT call metrics
- [ ] **OBS-03**: System instruments all inbound and outbound HTTP requests and database queries with OpenTelemetry traces (spans exported via OTLP); trace context propagates through background processing
- [ ] **OBS-04**: System emits structured JSON logs with per-request context (phone hash, message_id, trace_id) on every inbound message and outbound reply

### Deployment (DEP)

- [ ] **DEP-01**: System runs locally via Docker Compose with a PostgreSQL service (pgvector-enabled image for local parity even though Pinecone is used for vectors)
- [ ] **DEP-02**: System exposes a `/health` endpoint returning service status, suitable for platform health checks
- [ ] **DEP-03**: System is deployable to Railway; deployment config (railway.toml or Dockerfile), environment variable documentation, and PostgreSQL service wiring included

---

## v2 Requirements (Deferred)

- Semantic job matching via Pinecone vector search (embeddings written in v1, query logic deferred)
- External task queue (Celery/ARQ/Dramatiq) if Railway BackgroundTasks proves insufficient at scale
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
- Semantic/pgvector matching — schema ready, feature deferred to v2
- Redis — rate limiting uses PostgreSQL TTL counters to avoid infrastructure dependency at v1 scale

---

## Requirement Traceability

| REQ-ID | Phase | Notes |
|--------|-------|-------|
| SEC-01 | Phase 1 | Must be first; broken signature validation is silent in dev, fatal in prod |
| SEC-02 | Phase 1 | Idempotency before any processing — cheap to add early, expensive to retrofit |
| SEC-03 | Phase 1 | Before GPT calls to prevent cost blowout |
| SEC-04 | Phase 1 | Audit table in initial migration |
| SEC-05 | Phase 4 | Wired in orchestration layer |
| IDN-01 | Phase 1 | Phone identity in initial schema |
| IDN-02 | Phase 1 | created_at in initial schema |
| EXT-01 | Phase 2 | Core GPT classification call |
| EXT-02 | Phase 2 | Job posting Pydantic schema + prompt |
| EXT-03 | Phase 2 | Worker goal Pydantic schema + prompt |
| EXT-04 | Phase 2 | Unknown message fallback reply |
| STR-01 | Phase 1 / Phase 2 | Schema in Phase 1; write in Phase 2 after extraction |
| STR-02 | Phase 1 / Phase 2 | Schema in Phase 1; write in Phase 2 after extraction |
| STR-03 | Phase 4 | Confirmation SMS in orchestration layer |
| VEC-01 | Phase 2 | Pinecone client init + embedding write at job creation |
| MATCH-01 | Phase 3 | Earnings math SQL query |
| MATCH-02 | Phase 3 | SMS reply formatter |
| MATCH-03 | Phase 3 | Empty match fallback reply |
| OBS-01 | Phase 2 | Braintrust wraps GPT calls in ExtractionService |
| OBS-02 | Phase 1 | Prometheus /metrics endpoint scaffolded with infrastructure |
| OBS-03 | Phase 1 | OTel instrumentation from day one; trace context in background tasks |
| OBS-04 | Phase 1 | structlog with request context |
| DEP-01 | Phase 1 | Docker Compose in initial setup |
| DEP-02 | Phase 1 | /health endpoint with infrastructure |
| DEP-03 | Phase 4 | Railway deployment config; Docker Compose dev → Railway prod translation |
