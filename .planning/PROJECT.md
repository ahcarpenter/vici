# Vici

## What This Is

A Python/FastAPI API that receives SMS messages via a single Twilio webhook and uses gpt-5.3-chat-latest to classify and extract structured data from natural language. Job posters text to create job listings; workers text their earnings goals and receive a ranked list of matching jobs. No app, no signup — just text.

## Core Value

A worker who texts their earnings goal must receive a ranked list of jobs that lets them hit that goal in the shortest possible time.

## Current Milestone: v1.1 De-platform — Docker-Only Base

**Goal:** Re-baseline the repo as a hosting-agnostic, Docker-only application. No GCP, no Kubernetes, no provider-specific deploy config.

**Target features:**
- Provider-neutral `docker-compose.prod.yml` as the canonical production deploy spec (healthchecks, restart policies, volume conventions)
- Temporal Cloud integration (replace in-cluster Temporal Helm chart)
- Postgres visibility for Temporal (drop OpenSearch entirely from the stack)
- Self-contained observability in compose for production (Jaeger + Prometheus + Grafana)
- Full GKE/GCP removal: delete `pulumi/`, `helm/`, `k8s/`, ESO config, `render.yaml`, and the `gks-refactor` workstream artifacts

## Requirements

### Validated

- [x] Single Twilio SMS webhook receives all inbound messages
- [x] gpt-5.3-chat-latest classifies each message as a job posting, a worker earnings goal, or unknown using a single structured-output call
- [x] Job posting extracts: description, ideal date/time, date/time flexibility, estimated duration (optional), location, pay/rate
- [x] Worker goal extracts: target earnings amount, target timeframe
- [x] Structured job postings stored in PostgreSQL; job embeddings written to Pinecone at creation time
- [x] Structured worker goals stored in PostgreSQL
- [x] Job matching uses earnings math: rate × estimated duration ≥ worker goal, sorted by soonest available / shortest duration (MatchService — Phase 03-01)

### Active

(v1.1 milestone requirements defined in `.planning/REQUIREMENTS.md`)

### Deferred (v1.0 Phase 04 — out of scope for v1.1)

- [ ] Job poster receives SMS confirmation summarizing extracted job details (unknown-branch graceful reply implemented; poster confirmation pending)
- [ ] Worker receives SMS reply with ranked list of matching jobs

### Out of Scope

- User registration or auth flows — phone number is identity, first text auto-registers
- Web UI or dashboard — API only for MVP
- Multiple Twilio phone numbers or routing logic — single inbound number
- Real-time push notifications — SMS reply is the only notification mechanism
- Payment processing — rate/pay is informational only in v1

## Architecture

### Layer Stack

```
SMS Webhook (POST /webhook/sms)
  └── 5-gate security chain (signature → idempotency → user → rate-limit → persist)
        └── Temporal workflow start (ProcessMessageWorkflow) → HTTP 200 to Twilio

Temporal ProcessMessageWorkflow (4 total attempts, failure handler activity on exhaustion)
  └── process_message_activity → PipelineOrchestrator.run()
        ├── ExtractionService (gpt-5.3-chat-latest classify+extract, Braintrust-wrapped)
        ├── JobRepository / WorkGoalRepository (flush-only, single commit per branch)
        └── write_job_embedding() → Pinecone (fire-and-forget; failure enqueued to pinecone_sync_queue)

Temporal SyncPineconeQueueWorkflow cron (*/5 * * * *)
  └── sync_pinecone_queue_activity — sweeps pinecone_sync_queue, retries failed embeddings
```

### Key Modules

| Module | Responsibility |
|--------|---------------|
| `src/sms/router.py` | Webhook route, 5-gate security chain |
| `src/sms/repository.py` | MessageRepository: idempotency, rate limiting, user CRUD |
| `src/extraction/service.py` | ExtractionService: GPT-only, returns discriminated union |
| `src/extraction/orchestrator.py` | PipelineOrchestrator: full pipeline (GPT → storage → Pinecone) |
| `src/extraction/schemas.py` | `ExtractionResult = JobExtraction \| WorkerExtraction \| UnknownMessage` |
| `src/temporal/activities.py` | Temporal activities: process_message, sync_pinecone_queue, handle failure |
| `src/temporal/workflows.py` | ProcessMessageWorkflow, SyncPineconeQueueWorkflow |
| `src/temporal/worker.py` | Worker runner, client factory, cron registration |
| `src/config.py` | Nested Pydantic Settings (4 sub-models via model_validator) |
| `src/metrics.py` | Prometheus metric singletons |

### Data Model (3NF)

```
users (id PK, phone_hash UNIQUE, created_at)
  └── messages (id PK, user_id FK, message_sid UNIQUE, body, created_at)
  └── rate_limit (user_id FK, window_start, count)

jobs (id PK, user_id FK, description, ideal_datetime, flexibility,
      estimated_duration, location, pay_rate, created_at)
  └── pinecone_sync_queue (id PK, job_id FK, status, retry_count)

work_goals (id PK, user_id FK, target_earnings, target_timeframe, created_at)

matches (id PK, job_id FK, work_goal_id FK, UNIQUE)
audit_log (id PK, message_id FK, raw_body, raw_gpt_response, created_at)
```

## Context

- Single Twilio webhook endpoint handles all message classification and routing
- gpt-5.3-chat-latest handles both classification and structured extraction in a single `beta.chat.completions.parse` call
- PipelineOrchestrator owns all pipeline logic (GPT → storage → Pinecone → Twilio reply)
- DI graph built in FastAPI lifespan: OpenAI client → ExtractionService → PipelineOrchestrator → Inngest module vars
- Pinecone is the vector store; PostgreSQL has no pgvector column
- Phone number extracted from Twilio request payload serves as the user identifier (stored as phone_hash)
- Deployment target: Render.com (web service + PostgreSQL via render.yaml Blueprint)
- Observability stack: structlog → stdout (JSON), OTel → Jaeger v2 (OpenSearch backend), Prometheus → Grafana

## Constraints

- **AI Model**: gpt-5.3-chat-latest (OpenAI) — specified by product owner; used via `beta.chat.completions.parse`
- **Embedding Model**: `text-embedding-3-small` (OpenAI, 1536 dims) for Pinecone vectors
- **Vector Store**: Pinecone (serverless) — job embeddings only; no pgvector
- **Database**: PostgreSQL 16 — structured storage, no vector columns
- **Framework**: Python + FastAPI (async, uv package manager)
- **Async Queue**: Inngest — event-driven, retries, cron; no FastAPI BackgroundTasks
- **Inbound Channel**: Twilio SMS only — no other input channels in v1
- **Identity**: Phone number only — no auth, no user management system
- **Deployment**: Render.com (render.yaml Blueprint); local dev via Docker Compose (8 services)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Single webhook endpoint for all message types | Simplifies Twilio config; AI classifier handles routing | Implemented — 5-gate chain |
| GPT classifies + extracts in same call | Reduces latency and token overhead vs. two-step approach | Implemented — `beta.chat.completions.parse` with discriminated union |
| Earnings math for v1 matching (not semantic) | Deterministic, testable, and directly answers the worker's question | Pending (Phase 3) |
| Pinecone for vectors (not pgvector) | External managed service; postgres:16 plain image for simplicity | Implemented — Pinecone serverless |
| ExtractionService is GPT-only; PipelineOrchestrator owns full pipeline | Separation of concerns; testable in isolation | Implemented — Phase 02.1 refactor |
| Flush-only repositories; caller controls transaction boundary | Single commit per pipeline branch prevents partial writes | Implemented |
| Nested Pydantic Settings via model_validator | Clean namespacing without breaking .env file | Implemented |
| Render.com deployment (not Vercel) | Persistent server, simpler than Vercel + ASGI adapter | Decided during Phase 02.5 |
| Inngest Cloud for production (Dev Server locally) | INNGEST_DEV=1 disables signing key requirement in dev | Implemented |
| ALWAYS_ON OTel sampler | Unambiguous trace coverage; no parent-based override confusion | Implemented — Phase 02.3 |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-01 — milestone v1.1 (De-platform — Docker-Only Base) started; v1.0 application requirements (webhook, classification, extraction, persistence, earnings-math matching) moved to Validated.*
