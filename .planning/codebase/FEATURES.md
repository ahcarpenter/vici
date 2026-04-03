# Features

> Last updated: 2026-04-03 | Confidence: HIGH | Source: codebase inspection, phase summaries

## Complete

### Phase 01: Foundation
- [x] Async FastAPI skeleton with lifespan DI
- [x] 5-gate Twilio webhook security chain (signature, rate limit, user lookup, message save, workflow dispatch)
- [x] 3NF schema: User, Message, Job, WorkGoal, RateLimit, AuditLog, PineconeSyncQueue
- [x] Alembic async migrations

### Phase 01.1: Schema Revision
- [x] User/Message/WorkGoal replace Phone/InboundMessage/Worker with integer FKs

### Phase 02: GPT Extraction
- [x] ExtractionService: GPT classify+extract via beta.chat.completions.parse (discriminated union)
- [x] JobPosting, WorkerGoal, Unknown message types
- [x] Pinecone embedding write with text-embedding-3-small
- [x] Failed Pinecone writes queued to PineconeSyncQueue for retry

### Phase 02.1: Persistence Refactor
- [x] Nested Pydantic Settings (db, twilio, openai, observability sub-models)
- [x] PipelineOrchestrator: single session.commit() per branch
- [x] Pinecone failure enqueued in separate session (no rollback coupling)

### Phase 02.3: Observability - Tracing
- [x] OpenTelemetry -> Jaeger v2 (OpenSearch backend)
- [x] ALWAYS_ON sampler
- [x] structlog JSON with OTel trace/span IDs
- [x] FastAPI and SQLAlchemy auto-instrumentation

### Phase 02.4: Observability - Metrics
- [x] Prometheus + Grafana with pre-provisioned dashboard
- [x] Custom counters: extraction success/failure, token usage, pipeline failures

### Phase 02.5: Production Hardening
- [x] Multi-stage Dockerfile (non-root, HEALTHCHECK)
- [x] render.yaml Blueprint
- [x] GitHub Actions CI (SQLite tests, ruff linting)
- [x] on_failure handler for pipeline errors (sends error SMS)

### Phase 02.7: README
- [x] Complete developer README with setup instructions

### Phase 02.8: Code Refactor
- [x] Repository pattern with base class
- [x] SOLID-aligned domain boundaries

### Phase 02.8.1: SOLID Refactor
- [x] Further SOLID alignment where warranted by churn

### Phase 02.9: Temporal Migration (replaced Inngest)
- [x] ProcessMessageWorkflow: 4 attempts, exponential backoff, on_failure activity
- [x] SyncPineconeQueueWorkflow: cron every 5 min with RPCError idempotency
- [x] Temporal worker started in FastAPI lifespan
- [x] Docker Compose temporal + temporal-ui services

### Phase 02.10: Temporal Distributed Tracing
- [x] TracingInterceptor on Client.connect() (worker inherits)
- [x] Manual span for sync_pinecone_queue activity with attributes

### Phase 02.11: Edge-Case Hardening
- [x] Config validation (Settings._validate_required_credentials)
- [x] GPT None guard in ExtractionService
- [x] Rate limit rolling window (Python datetime for SQLite compatibility)
- [x] Webhook field validation
- [x] Graceful shutdown timeout
- [x] Handler error catches with structured logging

### Phase 02.12: Domain Canonicalization
- [x] PipelineOrchestrator moved to src/pipeline/orchestrator.py
- [x] Handler registry pattern (Chain of Responsibility): base.py, job_posting.py, worker_goal.py, unknown.py
- [x] PipelineContext dataclass for handler arguments
- [x] Inngest replaced by Temporal; inngest_client.py deleted
- [x] DI bug fix: repos instantiated and wired to handlers in lifespan

## Not Started

### Phase 03: Earnings Math Matching
- [ ] MatchService: earnings math SQL, ranked results
- [ ] SMS formatter for ranked job list
- [ ] Empty-match fallback SMS

### Phase 04: Outbound SMS and Deploy
- [ ] Outbound SMS for job posters and workers
- [ ] STOP/START pass-through
- [ ] Render.com production deploy validation
