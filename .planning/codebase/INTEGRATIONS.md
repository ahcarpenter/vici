# External Integrations

**Analysis Date:** 2026-04-22

---

## APIs & External Services

### OpenAI

- **Purpose:** GPT classification of inbound SMS messages; text-embedding generation for Pinecone upserts
- **Entry points:**
  - Client instantiated: `src/main.py:129–134` (`wrap_openai(AsyncOpenAI(...))`)
  - GPT structured output: `src/extraction/service.py:90` (`client.beta.chat.completions.parse`)
  - Embeddings: `src/extraction/utils.py:14` (`openai_client.embeddings.create`)
- **SDK:** `openai 2.26.0` (AsyncOpenAI)
- **Auth:** `OPENAI_API_KEY` env var → `src/config.py:58` → `ExtractionSettings.openai_api_key`
- **Model:** `gpt-5.3-chat-latest` (`src/extraction/constants.py:1`) for classification; `text-embedding-3-small` (1536 dims) for embeddings
  - **Flag:** `gpt-5.3-chat-latest` is not a recognized OpenAI model name as of the analysis date. This may be a placeholder, a private preview identifier, or a typo. Verify it resolves to a deployed model before production use.
- **Retry config:** `tenacity` decorator on `ExtractionService._call_with_retry` (`src/extraction/service.py:80–88`): max 4 attempts, random exponential backoff 1–60s, retries on `RateLimitError` and `APIStatusError`. `max_retries=0` on the `AsyncOpenAI` client itself (SDK-level retries disabled; tenacity handles it). Timeout per call: 30s (`GPT_CALL_TIMEOUT_SECONDS`, `src/extraction/constants.py:11`).
- **Failure mode:** `ApplicationError(non_retryable=False)` raised if GPT returns an unparseable response, causing Temporal to retry the activity up to `PROCESS_MSG_RETRY_MAX_ATTEMPTS` (4) times.
- **Observability:** Call count, duration, and token usage tracked via Prometheus counters/histograms in `src/metrics.py`; OTel span `gpt.classify_and_extract` in `src/extraction/service.py:58`.

---

### Pinecone

- **Purpose:** Vector store for job posting embeddings; used to find semantically similar jobs for worker goal matching
- **Entry points:**
  - Write path: `src/extraction/utils.py:6` (`write_job_embedding`)
  - Called from: `src/pipeline/handlers/job_posting.py`, `src/temporal/activities.py:123` (`sync_pinecone_queue_activity`)
- **SDK:** `pinecone[asyncio] 8.1.0` (`PineconeAsyncio`, `Vector`)
- **Auth:** `PINECONE_API_KEY` → `src/config.py:59`; `PINECONE_INDEX_HOST` → `src/config.py:60`
- **Connection pattern:** New `PineconeAsyncio` context manager opened per `write_job_embedding` call (`src/extraction/utils.py:20`). No persistent client or connection pool.
  - **Flag:** A new Pinecone client is instantiated on every embedding write. For the `sync_pinecone_queue_activity` which may process up to 50 rows (`LIMIT 50` in `src/temporal/activities.py:112`), this creates up to 50 separate client connections per sweep. Should be refactored to a single client per activity invocation.
- **Retry config:** No explicit retry wrapper around Pinecone calls. Failures in `sync_pinecone_queue_activity` are caught per-row, the row is marked `status='failed'` in `pinecone_sync_queue`, and processing continues. The Temporal workflow for sync has `RetryPolicy(maximum_attempts=1)` — no workflow-level retry.
- **Failure mode:** Per-row failures logged as warnings and counted via `failed` counter. Failed rows remain in `pinecone_sync_queue` with `status='failed'` and incremented `retry_count` but are not re-queued automatically — they will be retried on the next cron sweep only if re-selected by the `status='pending'` filter, which they will not be since status is set to `'failed'`.
  - **Flag:** Once a row transitions to `status='failed'`, it is never re-queued. There is no dead-letter re-enqueue logic for Pinecone sync failures.
- **Queue depth metric:** `pinecone_sync_queue_depth` gauge polled every 15s via background task in `src/main.py:90–119`.

---

### Twilio

- **Purpose:** Inbound SMS webhook receiver and outbound SMS reply sender
- **Entry points:**
  - Webhook receiver: `src/sms/router.py:24` (`POST /webhook/sms`)
  - Signature validation: `src/sms/dependencies.py:47` (`validate_twilio_request`)
  - Outbound SMS: `src/pipeline/handlers/unknown.py` (via `TwilioClient`)
  - Client instantiated: `src/main.py:139`
- **SDK:** `twilio 9.10.2` (`twilio.rest.Client`, `twilio.request_validator.RequestValidator`)
- **Auth:**
  - Inbound webhook: HMAC-SHA1 signature validated via `RequestValidator` using `TWILIO_AUTH_TOKEN`; `src/sms/dependencies.py:59–63`
  - Outbound: `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` → `TwilioClient` constructor
  - Signature validation **bypassed in `ENV=development`** (`src/sms/dependencies.py:57`).
- **Failure mode:** `TwilioSignatureInvalid` exception raises HTTP 403 (handler in `src/exceptions.py`). No retry on outbound SMS failures.
- **Retry config:** None. Outbound Twilio calls are synchronous/blocking; no tenacity wrapper.
- **Rate limiting:** Application-level sliding window enforced by `MessageRepository.enforce_rate_limit` — max 5 messages per 60s per user by default (`src/config.py:13–14`).

---

### Braintrust

- **Purpose:** LLM observability / experiment tracing — wraps the OpenAI client to log prompts and completions
- **Entry points:**
  - `src/main.py:7` (`from braintrust import wrap_openai`) — wraps `AsyncOpenAI` at startup
  - `src/extraction/service.py:6,35` (`from braintrust import init_logger; _bt_logger = init_logger(project="vici")`)
- **SDK:** `braintrust 0.8.0`
- **Auth:** `BRAINTRUST_API_KEY` → `src/config.py:64`. **Note:** not in `Settings._validate_required_credentials`, so startup does not fail if unset. The SDK silently no-ops when the key is absent.
- **Failure mode:** Graceful degradation — Braintrust is a tracing wrapper; if the API key is missing or the Braintrust API is down, the wrapped `AsyncOpenAI` client continues to function normally.
- **Retry config:** Not applicable (fire-and-forget tracing).

---

## Data Storage

### PostgreSQL (Cloud SQL)

- **Provider:** GCP Cloud SQL (`POSTGRES_16`), `infra/components/database.py:57`
- **Instance names:** `vici-app-{env}` (app DB), `vici-temporal-{env}` (Temporal DB)
- **Connection:** `DATABASE_URL` env var (unix socket via Cloud SQL Auth Proxy in production; direct TCP in local docker-compose)
  - Production: Cloud SQL Auth Proxy v2.14.1 as native K8s sidecar (unix socket at `/cloudsql`)
  - Local: `postgres:16` container, port 5432
- **Client:** `asyncpg 0.31.0` via `sqlalchemy 2.0.48` async engine (`create_async_engine`), `src/database.py:21–23`
- **Session management:** `async_sessionmaker` with `expire_on_commit=False`, `src/database.py:26–27`
- **Migrations:** Alembic (`alembic 1.18.4`), `migrations/versions/`, run as a K8s Job before deployment (`infra/components/migration.py`)
- **Schema:** 3NF. Tables: `user`, `message`, `job`, `work_goal`, `match`, `sms_audit_log`, `pinecone_sync_queue`
- **HA:** REGIONAL in prod, ZONAL in dev/staging. Backups disabled in dev (`infra/components/database.py:27–31`).
- **Auth:** Workload Identity (GKE service account annotated with GCP service account) — no static key files.
- **Failure mode:** `readyz` endpoint (`src/main.py:207–218`) returns 503 if DB is unreachable. No automatic reconnect logic beyond SQLAlchemy's default pool behavior.

---

## Workflow Orchestration

### Temporal

- **Purpose:** Durable execution for SMS processing pipeline and Pinecone sync cron job
- **Entry points:**
  - Client connection: `src/temporal/worker.py:17` (`Client.connect(address, interceptors=[TracingInterceptor()])`)
  - Worker startup: `src/temporal/worker.py:28` (`run_worker`)
  - Cron registration: `src/temporal/worker.py:47` (`start_cron_if_needed`)
  - Workflow dispatch: `src/sms/service.py:25` (`client.start_workflow(ProcessMessageWorkflow.run, ...)`)
- **SDK:** `temporalio 1.24.0`
- **Auth:** No TLS or auth token by default. `TEMPORAL_ADDRESS` is plain `host:port` (`localhost:7233` for local, cluster-internal service for prod).
  - **Flag:** No mTLS or API key configured on the Temporal client. Production traffic travels over the GKE cluster network (ClusterIP service `temporal-frontend.temporal.svc.cluster.local:7233`) which provides network-level isolation, but there is no application-layer auth.
- **Workflows:**
  - `ProcessMessageWorkflow` — triggered per inbound SMS; runs `process_message_activity` with retry policy (4 attempts, 1s initial, 2x backoff, 5m max interval, 60s start-to-close timeout). On exhaustion, runs `handle_process_message_failure_activity` (1 attempt, 10s timeout).
  - `SyncPineconeQueueWorkflow` — cron (`*/5 * * * *`); runs `sync_pinecone_queue_activity` (1 attempt, 120s timeout).
- **Retry config:** Defined as constants in `src/temporal/constants.py`. All timeouts and retry policies are explicit.
- **Failure mode:** `ApplicationError(non_retryable=True)` halts retries immediately (used when DB row not found, `src/temporal/activities.py:61–64`). Worker shutdown uses a 10s `asyncio.wait_for` timeout (`WORKER_SHUTDOWN_TIMEOUT_SECONDS`, `src/main.py:179`).
- **Observability:** OTel tracing via `temporalio.contrib.opentelemetry.TracingInterceptor` (`src/temporal/worker.py:22`); spans exported to Jaeger collector.
- **Production deployment:** Temporal Helm chart `0.74.0` (server `1.29.1`), OpenSearch as visibility store, Cloud SQL Auth Proxy as sidecar for DB connectivity. Defined in `infra/components/temporal.py`.
- **Local dev:** `temporalio/auto-setup:1.26.2` (server `1.26`) — **3-minor-version behind production**.

---

## Observability Stack

### OpenTelemetry → Jaeger

- **Purpose:** Distributed tracing across FastAPI requests, SQLAlchemy queries, and Temporal activities
- **Entry point:** `src/main.py:70–87` (`_configure_otel`)
- **Exporter:** `OTLPSpanExporter` (gRPC), endpoint from `OTEL_EXPORTER_OTLP_ENDPOINT` → `src/config.py:62`
- **Instrumentation:** `FastAPIInstrumentor` (auto), `SQLAlchemyInstrumentor` (auto), manual spans in `src/extraction/service.py`, `src/temporal/activities.py`, `src/matches/service.py`
- **Jaeger collector:** `jaegertracing/jaeger:2.16.0` — OTLP gRPC port 4317. Stores traces in OpenSearch. `infra/components/jaeger.py`
- **Sampling:** `ALWAYS_ON` (`src/main.py:84`)
- **Failure mode:** If Jaeger/OTel endpoint is unreachable, the `BatchSpanProcessor` drops spans silently. Application continues normally.

### Prometheus + Grafana

- **Purpose:** Metrics collection and dashboarding
- **Metrics exposed:** `/metrics` endpoint via `prometheus-fastapi-instrumentator 7.1.0` (`src/main.py:190`)
- **Custom metrics:** `src/metrics.py` — `gpt_calls_total`, `gpt_call_duration_seconds`, `gpt_input_tokens_total`, `gpt_output_tokens_total`, `pinecone_sync_queue_depth`, `pipeline_failures_total`, `temporal_queue_depth` (stub gauge, always 0)
- **Production:** `kube-prometheus-stack` Helm chart `69.8.2`; `ServiceMonitor` CR in `infra/components/prometheus.py:209`. Grafana datasources: Prometheus + Jaeger. Dashboards: FastAPI (from `grafana/provisioning/dashboards/fastapi.json`) and Temporal (Grafana.com dashboard ID 17900).
- **Local dev:** `prom/prometheus:v3.1.0` + `grafana/grafana:11.4.0` in `docker-compose.yml`

### OpenSearch

- **Purpose:** Backend storage for Jaeger traces and Temporal workflow visibility
- **Entry points:** Jaeger collector config (`infra/components/jaeger.py:65`), Temporal Helm values (`infra/components/temporal.py:192–208`)
- **Version:** `2.37.0` (Helm chart), `2.19.4` (docker-compose image). Held at 2.x — OpenSearch 3 breaks Temporal's ES client.
- **Auth:** Security plugin disabled (`plugins.security.disabled: true`, `infra/components/opensearch.py:63`). No auth on the OpenSearch endpoint.
  - **Flag:** OpenSearch runs with security disabled in all environments. Acceptable only because it is cluster-internal (no Ingress). Ensure network policies prevent external access.
- **Single-node deployment:** `singleNode: True`, 10Gi PVC, no replica redundancy.

---

## Authentication & Identity

**Auth Provider:** No end-user authentication. The application authenticates inbound requests via Twilio webhook signature validation only.

**GCP Workload Identity:**
- All GKE workloads authenticate to GCP APIs via Workload Identity (KSA → GSA annotation)
- No static service account key files anywhere in the codebase
- WIF (Workload Identity Federation) used for GitHub Actions CI/CD (`infra/components/cd.py`)

**Secrets management:**
- All runtime secrets stored in GCP Secret Manager, named `{env}-{slug}` (e.g., `dev-openai-api-key`)
- External Secrets Operator (`external-secrets 1.3.2`) syncs them to K8s Secrets every 1h (`infra/components/secrets.py:15`)
- 11 secrets defined in `_SECRET_DEFINITIONS` (`infra/components/secrets.py:19–32`)

---

## CI/CD

**Hosting:** GKE Autopilot (us-central1), GCP Artifact Registry

**CI Pipeline:** GitHub Actions
- `ci.yml` — runs on push/PR to `main`: ruff lint, ruff format check, pytest
- `cd-dev.yml` → `cd-base.yml` — builds Docker image, pushes to Artifact Registry, runs `pulumi up` for dev stack, health-checks `https://dev.usevici.com/health`
- `cd-staging.yml`, `cd-prod.yml` — same base workflow with env-specific gates

**Pulumi state:** GCS bucket per environment; lock cleared via `pulumi cancel` on workflow start (`cd-base.yml:114–119`)

---

## Webhooks & Callbacks

**Incoming:**
- `POST /webhook/sms` — Twilio inbound SMS webhook (`src/sms/router.py:24`)
  - Validated via `X-Twilio-Signature` HMAC-SHA1 (`src/sms/dependencies.py:59`)
  - Public URL constructed from `WEBHOOK_BASE_URL` env var (`src/sms/dependencies.py:40–44`)
  - Returns empty TwiML `<Response/>` to Twilio immediately; processing is async via Temporal

**Outgoing:**
- Twilio SMS replies sent from `src/pipeline/handlers/unknown.py` (unknown message type)

---

## Environment Configuration Summary

| Variable | Required | Consumer | Notes |
|---|---|---|---|
| `DATABASE_URL` | Yes | `src/database.py` | Postgres connection string |
| `TWILIO_AUTH_TOKEN` | Yes | `src/sms/dependencies.py`, `src/main.py` | Signature validation + outbound auth |
| `TWILIO_ACCOUNT_SID` | No (startup) | `src/main.py:139` | Outbound SMS; defaults empty |
| `TWILIO_FROM_NUMBER` | No (startup) | `src/config.py` | Source phone number |
| `OPENAI_API_KEY` | Yes | `src/main.py:131` | GPT + embeddings |
| `PINECONE_API_KEY` | Yes | `src/extraction/utils.py` | Vector upserts |
| `PINECONE_INDEX_HOST` | No (startup) | `src/extraction/utils.py` | Defaults empty; upserts will fail silently if unset |
| `TEMPORAL_ADDRESS` | Yes | `src/main.py:167` | Temporal frontend service |
| `WEBHOOK_BASE_URL` | Yes | `src/sms/dependencies.py` | Canonical public URL for Twilio signature |
| `ENV` | Yes | `src/config.py`, `src/sms/dependencies.py` | Controls signature validation bypass in `development` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | No | `src/main.py:81` | Jaeger OTLP gRPC endpoint; spans dropped if unset |
| `BRAINTRUST_API_KEY` | No | `src/main.py:7`, `src/extraction/service.py:35` | LLM tracing; silent no-op if absent |
| `GIT_SHA` | No | `src/config.py:65` | Injected as `service.version` OTel resource attribute; defaults `"dev"` |

---

*Integration audit: 2026-04-22*
