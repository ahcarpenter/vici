# External Integrations

**Analysis Date:** 2026-04-06

## APIs & External Services

**AI / LLM:**
- OpenAI - SMS message classification, structured data extraction, text embeddings
  - SDK/Client: `openai` (AsyncOpenAI), wrapped with `braintrust.wrap_openai`
  - Models used: `gpt-5.3-chat-latest` (classification), `text-embedding-3-small` (embeddings, 1536 dims)
  - Auth env var: `OPENAI_API_KEY`
  - Entry points: `src/extraction/service.py` (classification), `src/extraction/utils.py` (embeddings)
  - Features used: `beta.chat.completions.parse` with Pydantic `response_format` for structured output
  - Retry: tenacity with exponential backoff, 4 max attempts (`src/extraction/constants.py`)
  - Timeout: 30s per call (`GPT_CALL_TIMEOUT_SECONDS`)

**LLM Observability:**
- Braintrust - LLM call tracing and evaluation
  - SDK/Client: `braintrust` (`wrap_openai`, `init_logger`)
  - Auth env var: `BRAINTRUST_API_KEY`
  - Usage: wraps OpenAI client at startup in `src/main.py` lifespan; project logger in `src/extraction/service.py`

**Vector Database:**
- Pinecone - Job posting embedding storage and similarity search
  - SDK/Client: `pinecone[asyncio]` (`PineconeAsyncio`, `IndexAsyncio`)
  - Auth env var: `PINECONE_API_KEY`
  - Index host env var: `PINECONE_INDEX_HOST`
  - Entry point: `src/extraction/utils.py` (`write_job_embedding`)
  - Operations: upsert vectors with metadata (`phone_hash`)
  - Sync mechanism: `pinecone_sync_queue` table in Postgres, swept every 5 min by Temporal cron workflow (`src/temporal/activities.py` `sync_pinecone_queue_activity`)

**SMS:**
- Twilio - Inbound/outbound SMS messaging
  - SDK/Client: `twilio` (`twilio.rest.Client`)
  - Auth env vars: `TWILIO_AUTH_TOKEN`, `TWILIO_ACCOUNT_SID`, `TWILIO_FROM_NUMBER`
  - Inbound webhook: `POST /webhook/sms` (`src/sms/router.py`)
  - Webhook validation: Twilio signature verification in dependency chain (`src/sms/dependencies.py`)
  - Rate limiting: per-user, configurable window (`SMS_RATE_LIMIT_WINDOW_SECONDS`, default 60s, max 5 per window)
  - Response format: empty TwiML XML

## Data Storage

**Databases:**
- PostgreSQL 16
  - Connection env var: `DATABASE_URL` (format: `postgresql+asyncpg://...`)
  - Client: SQLModel / SQLAlchemy async (`src/database.py`)
  - Session factory: `async_sessionmaker` with `lru_cache` engine singleton
  - Tables (3NF): `user`, `message`, `job`, `work_goal`, `match`, `rate_limit`, `audit_log`, `pinecone_sync_queue`
  - Migrations: Alembic (`migrations/versions/`)
  - Production: Cloud SQL (separate instances for app and Temporal) via `infra/components/database.py`
  - CI: SQLite via aiosqlite

**Vector Storage:**
- Pinecone (see APIs section above)
  - Embedding model: `text-embedding-3-small` (1536 dimensions)
  - Index keyed by job ID, metadata includes `phone_hash`

**File Storage:**
- None (no file/blob storage used)

**Caching:**
- None (no Redis or other cache layer)

## Workflow Orchestration

**Temporal:**
- Server: `temporalio/auto-setup:1.26.2` (local), GKE Helm chart (prod) via `infra/components/temporal.py`
- SDK: `temporalio` (>=1.24.0)
- Connection: `src/temporal/worker.py` `get_temporal_client()` with OTel `TracingInterceptor`
- Auth env var: `TEMPORAL_ADDRESS`
- Task queue: `vici-queue` (configurable via `TEMPORAL_TASK_QUEUE`)

**Workflows:**
- `ProcessMessageWorkflow` - Processes inbound SMS through pipeline (4 retries, exponential backoff, failure handler activity)
- `SyncPineconeQueueWorkflow` - Cron every 5 min, sweeps `pinecone_sync_queue` table and upserts to Pinecone

**Activities:**
- `process_message_activity` - Runs `PipelineOrchestrator` for a single message
- `handle_process_message_failure_activity` - Logs permanent failures, increments Prometheus counter
- `sync_pinecone_queue_activity` - Batch upsert pending rows to Pinecone (limit 50 per sweep)

## Authentication & Identity

**Auth Provider:**
- Custom (no OAuth/SSO provider)
  - Users identified by phone number hash (`phone_hash`)
  - User upsert on first inbound SMS (`src/sms/dependencies.py`)
  - Webhook security via Twilio signature validation

**Infrastructure Auth:**
- GCP Workload Identity Federation for CI/CD (no static keys)
  - WIF pool and provider: `infra/components/cd.py`
  - Kubernetes service accounts with GCP IAM bindings: `infra/components/iam.py`, `infra/components/identity.py`

## Monitoring & Observability

**Distributed Tracing:**
- OpenTelemetry SDK -> Jaeger v2 (via OTLP/gRPC)
  - Configured in `src/main.py` `_configure_otel()`
  - Exporter endpoint env var: `OTEL_EXPORTER_OTLP_ENDPOINT`
  - Service name: `vici` (configurable via `OTEL_SERVICE_NAME`)
  - Auto-instrumented: FastAPI routes, SQLAlchemy queries
  - Manual spans: GPT calls (`src/extraction/service.py`), Temporal activities (`src/temporal/activities.py`), match pipeline (`src/matches/service.py`)
  - Temporal propagation: `TracingInterceptor` on client connection

**Jaeger:**
- Jaeger v2 (2.16.0) with OpenSearch backend
  - Collector: receives OTLP on ports 4317 (gRPC) / 4318 (HTTP)
  - Query UI: port 16686
  - Config: `jaeger/collector-config.yaml`, `jaeger/query-config.yaml`
  - Production: GKE deployments via `infra/components/jaeger.py`

**Metrics:**
- Prometheus + Grafana
  - Auto-metrics: `prometheus-fastapi-instrumentator` on all routes (`/metrics` endpoint)
  - Custom metrics in `src/metrics.py`:
    - `gpt_calls_total` (Counter, by classification_result)
    - `gpt_call_duration_seconds` (Histogram, buckets: 0.5-30s)
    - `gpt_input_tokens_total` / `gpt_output_tokens_total` (Counters)
    - `pinecone_sync_queue_depth` (Gauge, polled every 15s)
    - `pipeline_failures_total` (Counter, by function)
    - `temporal_queue_depth` (Gauge, stub/placeholder)
  - Prometheus config: `prometheus/prometheus.yml`
  - Grafana provisioning: `grafana/provisioning/dashboards/`, `grafana/provisioning/datasources/`
  - Production: kube-prometheus-stack Helm chart (`infra/components/prometheus.py`)

**Logs:**
- structlog with JSON rendering (`src/main.py` `_configure_structlog()`)
- OTel context injection: `trace_id` and `span_id` added to every log event
- Log level: INFO (filtering bound logger)

**Error Tracking:**
- No dedicated error tracking service (Sentry, etc.)
- Errors logged via structlog; permanent Temporal failures tracked by `pipeline_failures_total` counter

## CI/CD & Deployment

**Hosting:**
- Google Cloud Platform - GKE (Google Kubernetes Engine)
  - Region: `us-central1`
  - Managed by Pulumi IaC (`infra/`)
  - Components: cluster, app deployment + HPA, ingress, cert-manager, ESO, Temporal, Jaeger, OpenSearch, Prometheus

**CI Pipeline:**
- GitHub Actions (`.github/workflows/ci.yml`)
  - Trigger: push/PR to main
  - Steps: checkout, uv setup, dependency install, ruff lint, pytest
  - Test env: SQLite (no external service deps)

**CD Pipeline:**
- GitHub Actions (`.github/workflows/cd-base.yml` reusable workflow)
  - Auth: GCP Workload Identity Federation
  - Steps: checkout, GCP auth, Docker build + push to Artifact Registry, Pulumi deploy
  - Image tagging: `{sha}` and `{stack}` tags
  - Per-environment workflows: `cd-dev.yml`, `cd-staging.yml`, `cd-prod.yml`

**Container Registry:**
- Google Artifact Registry (`us-central1-docker.pkg.dev/{project}/vici-images/vici`)
- Managed by `infra/components/registry.py`

## Environment Configuration

**Required env vars (app will not start without these):**
- `DATABASE_URL` - PostgreSQL connection string
- `TWILIO_AUTH_TOKEN` - Twilio webhook signature validation
- `OPENAI_API_KEY` - GPT and embedding API access
- `PINECONE_API_KEY` - Vector database access
- `TEMPORAL_ADDRESS` - Temporal server connection
- `WEBHOOK_BASE_URL` - Base URL for Twilio webhook callbacks
- `ENV` - Environment identifier

**Optional env vars (have defaults):**
- `TWILIO_ACCOUNT_SID`, `TWILIO_FROM_NUMBER` - SMS sending (default: empty string)
- `PINECONE_INDEX_HOST` - Pinecone index endpoint (default: empty string)
- `OTEL_EXPORTER_OTLP_ENDPOINT` - Jaeger collector endpoint (default: empty string)
- `OTEL_SERVICE_NAME` - Trace service name (default: `vici`)
- `BRAINTRUST_API_KEY` - LLM observability (default: empty string)
- `GIT_SHA` - Service version for traces (default: `dev`)
- `TEMPORAL_TASK_QUEUE` - Temporal task queue name (default: `vici-queue`)
- `CRON_SCHEDULE_PINECONE_SYNC` - Pinecone sync frequency (default: `*/5 * * * *`)
- `SMS_RATE_LIMIT_WINDOW_SECONDS` - Rate limit window (default: 60)

**Secrets location:**
- Local dev: `.env.*` files (gitignored)
- Production: GCP Secret Manager via External Secrets Operator (`infra/components/secrets.py`)

## Webhooks & Callbacks

**Incoming:**
- `POST /webhook/sms` - Twilio inbound SMS webhook (`src/sms/router.py`)
  - Validates Twilio signature
  - Persists message to DB
  - Emits Temporal workflow for async processing
  - Returns empty TwiML XML

**Outgoing:**
- None detected (no outbound webhook registrations)

## Health Endpoints

- `GET /health` - Liveness probe (always returns `{"status": "ok"}`)
- `GET /readyz` - Readiness probe (checks DB connectivity, returns 503 if degraded)
- `GET /metrics` - Prometheus metrics scrape endpoint

---

*Integration audit: 2026-04-06*
