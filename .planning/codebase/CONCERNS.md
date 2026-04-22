# Codebase Concerns

**Analysis Date:** 2026-04-22

---

## Security

### [Critical] Twilio Signature Validation Bypassed in Development

- **Evidence:** `src/sms/dependencies.py:57`
- **Impact:** Any unauthenticated POST to `/webhook/sms` with a valid form body is accepted when `ENV=development`. If the application is deployed with `ENV=development` (or the variable is misconfigured), the entire authentication layer is disabled. An attacker who can reach the endpoint can inject arbitrary messages.
- **Recommended fix:** Remove the bypass entirely. Use the real Twilio test credentials (the Twilio test magic numbers) to validate signatures in local/dev environments. If a bypass is truly needed, gate it behind an explicit `DISABLE_TWILIO_SIGNATURE_VALIDATION=true` flag that can never be set `"true"` in infra manifests, and add a startup warning.

---

### [High] Raw E.164 Phone Numbers Written to Structured Logs (PII Leak)

- **Evidence:** `src/pipeline/handlers/unknown.py:61` — `log.info("unknown_reply_sent", message_sid=ctx.message_sid, to=ctx.from_number)`
- **Impact:** Every time an unknown message is handled, the sender's E.164 phone number is emitted to stdout as a structured JSON log field. This log is shipped to Jaeger/OTLP and potentially to any log aggregator. Phone numbers are PII and in many jurisdictions are regulated under GDPR/CCPA.
- **Recommended fix:** Replace `to=ctx.from_number` with `to_hash=hash_phone(ctx.from_number)` — consistent with how every other log site treats the number.

---

### [High] Raw E.164 Phone Number Persisted in Audit Log Detail Column

- **Evidence:** `src/sms/router.py:52` — `detail=json.dumps(dict(form_data))` where `form_data` contains `"From": "+1XXXXXXXXXX"`
- **Impact:** The full Twilio form payload (including the sender's E.164 phone number) is stored verbatim in `audit_log.detail`. The `audit_log` table has no row-level encryption, so any DB read exposes PII. This is a GDPR/CCPA compliance concern.
- **Recommended fix:** Scrub PII fields before writing to the audit log: `{**form_data, "From": hash_phone(form_data.get("From", ""))}`.

---

### [High] Unsalted SHA-256 Phone Hash — Vulnerable to Enumeration Attack

- **Evidence:** `src/sms/service.py:6-12`
- **Impact:** SHA-256 of E.164 numbers is deterministic and enumerable. The E.164 namespace for US numbers is ~10 billion values — trivially enumerable with a GPU. An attacker with DB access can reverse all `phone_hash` values to real numbers using a precomputed lookup table.
- **Recommended fix:** Use HMAC-SHA-256 with a secret key from env: `hmac.new(key=secret.encode(), msg=number.encode(), digestmod='sha256').hexdigest()`. Store the key as `PHONE_HASH_SECRET` in the same secrets store as other credentials.

---

### [High] `/metrics` Endpoint Publicly Exposed Without Authentication

- **Evidence:** `src/main.py:190` — `Instrumentator().instrument(app).expose(app)`
- **Impact:** The Prometheus `/metrics` endpoint is mounted on the same public port (8000) as the webhook, with no authentication. It exposes internal counters, queue depths, and service topology. An attacker can use it to understand system internals and detect anomalies in processing rates.
- **Recommended fix:** Either expose `/metrics` on a separate internal port only reachable within the cluster, or restrict via network policy. Minimally, the Kubernetes `NetworkPolicy` should block external traffic to `/metrics`.

---

### [High] OpenAPI/Swagger Docs Always Exposed — No Production Gate

- **Evidence:** `src/main.py:187` — `app = FastAPI(lifespan=lifespan)` with no `openapi_url=None` in production
- **Impact:** FastAPI serves `/docs` and `/openapi.json` in production by default. This exposes the full API schema, endpoint signatures, and request/response shapes publicly, aiding reconnaissance.
- **Recommended fix:** Per `AGENTS.md` guidance: add `"openapi_url": None, "docs_url": None, "redoc_url": None` to `app_configs` when `settings.env == "production"`.

---

### [Medium] `phone_e164` Never Populated from SMS Inbound Path

- **Evidence:** `src/sms/dependencies.py:92` — `UserRepository.get_or_create(session, phone_hash)` — `phone_e164` argument omitted
- **Impact:** Every user created through the SMS webhook has `phone_e164=None`. The match SMS formatter (`src/matches/formatter.py:50`) outputs `phone = cand.poster_phone or "N/A"` — workers receive "N/A" instead of a callable phone number. The core business function (workers calling job posters) is silently broken for all SMS-originated users.
- **Recommended fix:** Pass `from_number` to `get_or_create`: `UserRepository.get_or_create(session, phone_hash, phone_e164=from_number)`. Update the `ON CONFLICT` clause to backfill `phone_e164 WHERE user.phone_e164 IS NULL`.

---

## Correctness / Bugs

### [Critical] `pinecone_sync_queue` Check Constraint Rejects Application Writes

- **Evidence:** `migrations/versions/2026-03-06_extraction_additions.py:66` — check constraint: `status IN ('pending', 'synced', 'failed')`. Application writes: `src/temporal/activities.py:134` — `SET status='success'`
- **Impact:** Every successful Pinecone sync attempt violates the DB check constraint, causing the UPDATE to fail with an `IntegrityError`. The row stays `pending` forever. The sync queue grows without bound. All job embeddings that needed a retry will never reach Pinecone, breaking job-to-worker matching via vector search.
- **Recommended fix:** Add a migration that changes the constraint to `status IN ('pending', 'success', 'failed')`, or change the application code to write `'synced'` consistently. Pick one and add a test.

---

### [High] Migration 003 References Non-Existent `work_request` Table

- **Evidence:** `migrations/versions/2026-04-03_normalize_3nf.py:22-24` — `op.drop_constraint("work_request_user_id_fkey", "work_request", ...)` and `op.drop_column("work_request", "user_id")`. The initial schema at `migrations/versions/2026-03-05_initial_schema.py:75` creates `work_goal`, never `work_request`.
- **Impact:** Running `alembic upgrade head` on a fresh database fails at revision 003. The application cannot be deployed to a new environment. Any deployment pipeline that applies migrations from scratch is broken.
- **Recommended fix:** Update lines 22–24 and 55–68 in `2026-04-03_normalize_3nf.py` to reference `work_goal` instead of `work_request`. Verify with a full `alembic upgrade head` run in CI.

---

### [High] Rate Limit INSERT Inserts Row Before Checking Count — TOCTOU + Schema Mismatch

- **Evidence:** `src/sms/repository.py:29-53` — The TODO comment acknowledges the production DB may still have `UNIQUE(user_id, created_at)` which causes an `IntegrityError` on every INSERT. The rolling-window code inserts a row then counts. The constraint from migration 001 was dropped in migration 003, but if any environment has not run 003, the INSERT raises and returns a 500 to Twilio (which retries, compounding the problem).
- **Impact:** Rate limiting silently fails in any environment not on revision >= 003. Additionally, inserting before checking means a rate-limited user still gets a `rate_limit` row added to the DB — slightly inflating future counts by 1.
- **Recommended fix:** Remove the TODO after confirming all environments are on revision >= 003. Restructure to COUNT first, then INSERT only if within the limit.

---

### [High] `process_message_activity` Session Lacks Explicit Transaction Context

- **Evidence:** `src/temporal/activities.py:54` — `async with get_sessionmaker()() as session:` opens a session without `async with session.begin():`. Handlers call `session.commit()` directly inside their `handle()` method.
- **Impact:** On Temporal retry (e.g., after a GPT timeout), handlers re-run against the same DB session context. If a partial flush occurred before the exception, the retry may hit `UNIQUE(message_id)` on the `job` or `work_goal` tables, raise an `IntegrityError`, and trip the `non_retryable=True` path — permanently failing the workflow for a transient error.
- **Recommended fix:** Wrap the handler body with `async with session.begin():` in `process_message_activity`, so that any exception rolls back the partial state and the retry starts clean.

---

### [Medium] `JobCreate` Schema Has `raw_sms` Field That Is Never Persisted

- **Evidence:** `src/jobs/schemas.py:19` — `raw_sms: str = Field(min_length=1, max_length=1600)`. `src/jobs/models.py` — no `raw_sms` column. `src/jobs/repository.py:61-75` — `Job(...)` constructor never passes `raw_sms`.
- **Impact:** `raw_sms` is validated by Pydantic in `JobCreate` and `WorkGoalCreate` but silently discarded. Audit trail for what raw SMS produced a given job is lost.
- **Recommended fix:** Add a migration to add `raw_sms TEXT` columns to `job` and `work_goal` tables, or remove the field from both schemas.

---

### [Medium] `_dp_select` `keep` Matrix Causes Memory Explosion Under Realistic Job Volumes

- **Evidence:** `src/matches/service.py:117-126` — `capacity = sum(c.earnings for c in candidates)`, then `keep = [[False] * (capacity + 1) for _ in range(n)]`
- **Impact:** For 1,000 jobs at average $200 pay (20,000 cents each), `capacity = 20,000,000`. The `keep` matrix is `1000 × 20,000,001 ≈ 19 GB`. A single `MatchService.match()` call OOMs the container. Even at 100 jobs × $500, the matrix is ~50 MB with O(n × capacity) time.
- **Recommended fix:** Cap `capacity` to `work_goal.target_earnings`: `capacity = min(sum(c.earnings for c in candidates), work_goal.target_earnings)`. No solution ever needs to exceed the goal. Additionally cap `n` at a practical maximum (e.g., 500 jobs).

---

### [Medium] `find_candidates_for_goal` Returns All Available Jobs With No Scope Filter

- **Evidence:** `src/jobs/repository.py:15-32` — no `work_goal` or user scope parameter. `src/matches/service.py:33` — called with `session` only.
- **Impact:** The DP algorithm evaluates every available job in the database regardless of geography, timing, or work goal target. As the platform scales, this is both a performance issue and produces semantically incorrect matches (e.g., Chicago worker matched to LA jobs).
- **Recommended fix:** Pass `work_goal` to `find_candidates_for_goal` and add a date-range filter based on `target_timeframe`. Add a `LIMIT` clause (see Performance section).

---

## Reliability / Availability

### [High] Temporal Emission Failure Produces Orphan Message Rows

- **Evidence:** `src/sms/router.py:46-58` — `async with session.begin():` persists message and audit row, then `await sms_service.emit_message_received_event(...)` is called outside the transaction with no try/except.
- **Impact:** If the Temporal server is unreachable, `client.start_workflow()` raises. FastAPI returns a 500 to Twilio. Twilio retries. The idempotency check detects the existing `message_sid` row and returns 200 without re-emitting to Temporal. The message is permanently stuck — DB row exists, no workflow ever runs, no pipeline processing occurs, user gets no response.
- **Recommended fix:** Wrap `emit_message_received_event` in try/except. On failure, log an error and return `EMPTY_TWIML` with HTTP 200 (so Twilio stops retrying), but also enqueue a retry in a persistent table drained by the cron worker.

---

### [High] `_gauge_task` Not Awaited on Shutdown — Potential Connection Leak

- **Evidence:** `src/main.py:182` — `_gauge_task.cancel()` followed by `provider.force_flush()`. There is no `await asyncio.wait_for(_gauge_task, ...)` after cancellation.
- **Impact:** The gauge updater may be mid-DB-query when cancelled. The task is cancelled but never awaited, suppressing `CancelledError` silently. On GKE rolling deploys, this causes unclosed DB connection warnings and may leave transactions open.
- **Recommended fix:** `try: await asyncio.wait_for(_gauge_task, timeout=5.0) except (asyncio.CancelledError, asyncio.TimeoutError): pass`

---

### [High] `sync_pinecone_queue_activity` Has No Row-Level Locking

- **Evidence:** `src/temporal/activities.py:105-115` — `SELECT ... WHERE q.status = 'pending' LIMIT 50` with no `FOR UPDATE SKIP LOCKED`. Status updates happen in a separate session opened per row.
- **Impact:** If Temporal schedules two concurrent `SyncPineconeQueueWorkflow` runs (cron overlap or manual trigger), both workers fetch the same 50 rows. Double-upserts to Pinecone and double OpenAI embedding calls occur, inflating cost. Status updates race.
- **Recommended fix:** Add `FOR UPDATE SKIP LOCKED` to the fetch query. Update status in the same session/transaction as the fetch.

---

### [Medium] `rate_limit` Table Grows Without Bound — No Pruning

- **Evidence:** `src/sms/repository.py:34-37` — one row inserted per inbound message. No `DELETE` or TTL anywhere in the codebase.
- **Impact:** On a production system receiving thousands of messages per day, the `rate_limit` table grows indefinitely. Index scans on `(user_id, created_at)` degrade over time.
- **Recommended fix:** Add a periodic cleanup: `DELETE FROM rate_limit WHERE created_at < NOW() - INTERVAL '24 hours'`. Run as a Temporal scheduled activity alongside the Pinecone sync.

---

### [Medium] DB Connection Pool Uses SQLAlchemy Defaults — No Explicit Sizing or Pre-Ping

- **Evidence:** `src/database.py:22-23` — `create_async_engine(settings.database_url, echo=False)` — no `pool_size`, `max_overflow`, `pool_timeout`, or `pool_pre_ping`.
- **Impact:** Default `pool_size=5`, `max_overflow=10`. Under concurrent Temporal activity execution, the gauge updater, and webhook handlers, connection exhaustion is possible. Without `pool_pre_ping=True`, stale connections after network interruptions fail silently until a request hits them.
- **Recommended fix:** `create_async_engine(url, pool_size=10, max_overflow=20, pool_pre_ping=True, pool_timeout=30)`.

---

### [Low] `provider.force_flush()` Called Without Timeout — Blocks Event Loop on Shutdown

- **Evidence:** `src/main.py:183`
- **Impact:** If the Jaeger/OTLP endpoint is unreachable during shutdown, `force_flush()` blocks the event loop for the full exporter timeout (up to 30 seconds by default), delaying pod termination.
- **Recommended fix:** `provider.force_flush(timeout_millis=5000)`.

---

## Performance

### [High] Unbounded DP `keep` Matrix (Duplicate of Correctness Finding)

- **Evidence:** `src/matches/service.py:117-126`
- See Correctness section for full analysis. Caps `capacity` at `work_goal.target_earnings` to bound memory.

---

### [Medium] `find_candidates_for_goal` Loads All Available Jobs Into Python Heap

- **Evidence:** `src/jobs/repository.py:28-32` — `result.scalars().all()` with no LIMIT.
- **Impact:** With a large job corpus, all `Job` ORM objects are loaded into heap before DP processing. At 100 KB per ORM object × 10,000 rows ≈ 1 GB RAM per `match()` call.
- **Recommended fix:** Add `.limit(MAX_CANDIDATES)` to the query (e.g., `MAX_CANDIDATES = 500`).

---

### [Medium] Pinecone Client Opens New HTTP Connection Per Sync Row

- **Evidence:** `src/extraction/utils.py:20-28` — `async with PineconeAsyncio(...) as pc: async with pc.IndexAsyncio(...) as idx:` opened inside the per-row loop in `src/temporal/activities.py:122-128`.
- **Impact:** For 50 pending rows per sweep, 50 independent Pinecone connections are established and torn down. HTTP connection setup overhead dominates latency.
- **Recommended fix:** Move the `PineconeAsyncio` context manager outside the per-row loop in `sync_pinecone_queue_activity` and reuse the client across all rows.

---

### [Low] `UserRepository.get_or_create` Uses Two DB Round-Trips on Hot Path

- **Evidence:** `src/users/repository.py:17-34` — `INSERT ... ON CONFLICT DO NOTHING` then a separate `SELECT`.
- **Impact:** Two round-trips per webhook call.
- **Recommended fix:** Use `INSERT ... ON CONFLICT DO NOTHING RETURNING *` and fall back to SELECT only when RETURNING is empty (PostgreSQL-safe since production is PostgreSQL).

---

## Tech Debt

### [High] Migration 003 Wrong Table Name (Stale `work_request` References)

- **Evidence:** `migrations/versions/2026-04-03_normalize_3nf.py:20-24, 55-68`
- See Correctness section. Blocks fresh-instance deployment.

---

### [High] TODO Comment Acknowledges Undeployed Schema Dependency in Production Code

- **Evidence:** `src/sms/repository.py:29-31`
- The migration (003) was written but the TODO was never removed. It creates confusion about whether the code is safe to deploy.
- **Recommended fix:** Remove the comment after confirming all environments are on revision >= 003.

---

### [High] `MatchService` and `format_match_sms` Are Fully Implemented but Never Invoked

- **Evidence:** `src/matches/service.py`, `src/matches/formatter.py` — no callers in `src/`. `WorkerGoalHandler` (`src/pipeline/handlers/worker_goal.py`) creates the work goal and commits, but never calls `MatchService.match()` or sends a reply SMS.
- **Impact:** The matching and SMS reply features are completely non-functional end-to-end. A worker who texts their earnings goal receives no job matches. The core product loop is incomplete.
- **Recommended fix:** In `WorkerGoalHandler._do_handle`, after committing the work goal, instantiate `MatchService`, call `match()`, format with `format_match_sms()`, and send the result via `asyncio.to_thread(twilio_client.messages.create, ...)`.

---

### [Medium] `temporal_queue_depth` Prometheus Gauge Is a Permanent Zero-Value Stub

- **Evidence:** `src/metrics.py:38-41` — comment: `"always reads 0; placeholder for future instrumentation"`
- **Impact:** Alerting on Temporal backpressure is impossible. During an incident, on-call engineers see a flat-zero gauge that provides no signal.
- **Recommended fix:** Implement real depth measurement via the Temporal SDK's `WorkflowService.count_workflows` with status filters, or remove the metric until it can be properly implemented.

---

### [Low] Dead `user_id` Field Passed to `JobCreate` Constructor

- **Evidence:** `src/pipeline/handlers/job_posting.py:45` — `JobCreate(user_id=ctx.user_id, ...)`. `src/jobs/schemas.py` does not define `user_id`. Pydantic silently discards the extra field.
- **Impact:** Silent field discard. No runtime error. Can mislead future developers who assume `user_id` flows through `JobCreate`.
- **Recommended fix:** Remove `user_id=ctx.user_id` from the `JobCreate(...)` constructor call.

---

### [Low] Accidental `~/` Directory Committed to Repo Root

- **Evidence:** Literal directory `~/` at repo root containing `.gemini/` subdirectory.
- **Impact:** Appears to be an accidental path expansion failure. Clutters the repo and may contain user-local configuration.
- **Recommended fix:** `git rm -r "~"` and add `~/` to `.gitignore`.

---

## Operational

### [High] Matching Feature Is Silently Non-Functional With No Operational Signal

- **Evidence:** `src/pipeline/handlers/worker_goal.py` — no `MatchService` call, no warning log, no metric increment when matching is skipped.
- **Impact:** Workers text earnings goals and receive no job matches. There is no operational signal that the matching path is incomplete. On-call has no visibility into this failure mode.
- **Recommended fix:** At minimum, add `log.warning("match_not_implemented", work_goal_id=wg.id)` post-commit until matching is wired up. Once implemented, add `match_attempts_total` counter and `match_duration_seconds` histogram.

---

### [Medium] `readyz` Probe Does Not Enforce a DB Query Timeout

- **Evidence:** `src/main.py:211-218` — `await session.execute(text("SELECT 1"))` with no timeout guard.
- **Impact:** If the DB is slow (not down), the readiness probe blocks indefinitely until the kubelet's probe timeout (default 1s) fires. The application is marked unready, but the DB connection is still held open. Under sustained DB slowness, this can exhaust the connection pool.
- **Recommended fix:** `await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=2.0)` and catch `asyncio.TimeoutError` to return 503.

---

### [Medium] Braintrust Logger Initialized at Import Time Without Credential Validation

- **Evidence:** `src/extraction/service.py:35` — `_bt_logger = init_logger(project="vici")` — `braintrust_api_key` is not in `_validate_required_credentials` (`src/config.py:88-108`).
- **Impact:** If `BRAINTRUST_API_KEY` is missing, `init_logger()` initializes silently. LLM call observability is degraded without any startup error or warning.
- **Recommended fix:** Add `braintrust_api_key` to `_validate_required_credentials`, or make the Braintrust wrapper conditional on key presence.

---

### [Low] Stale `INNGEST_DEV` and `INNGEST_BASE_URL` Vars in CI Workflow

- **Evidence:** `.github/workflows/ci.yml:36-37`
- **Impact:** Inngest is not a dependency anywhere in `src/` or `pyproject.toml`. These are stale references from a previous architecture. They create confusion for new engineers about active integrations.
- **Recommended fix:** Remove the Inngest env vars from `ci.yml`.

---

## Dependency Hygiene

### [Medium] `psycopg2-binary` Is a Production Dependency When Only Needed for Migrations

- **Evidence:** `pyproject.toml:19` — `psycopg2-binary>=2.9.11` listed under `[project] dependencies`
- **Impact:** `psycopg2-binary` is only needed by Alembic's sync migration runner. The application uses `asyncpg` for all async DB traffic. Including `-binary` in the production image pulls in pre-compiled C extensions with a bundled OpenSSL version the psycopg2 maintainers explicitly warn against for production.
- **Recommended fix:** Move `psycopg2-binary` to `[dependency-groups] dev` or a dedicated `migration` extra if the migration K8s Job has a separate image.

---

### [Low] `openai` Dependency Has No Upper Version Bound

- **Evidence:** `pyproject.toml:11` — `"openai>=1.0.0"`. Locked at `2.26.0`.
- **Impact:** `uv update` can pull in a future major version (3.x) that breaks the `beta.chat.completions.parse` API used in `src/extraction/service.py:90`.
- **Recommended fix:** `openai>=2.0.0,<3.0.0`.

---

### [Low] No CVE Scanning in CI Pipeline

- **Evidence:** `.github/workflows/ci.yml` — no `pip-audit` or `uv audit` step.
- **Impact:** Transitive dependencies (e.g., `pyjwt 2.11.0`, `requests 2.32.5`) are not checked for known CVEs on each PR. Vulnerabilities can accumulate undetected.
- **Recommended fix:** Add `uv run pip-audit` or `uv audit` as a CI step. Run on every push to main.

---

*Concerns audit: 2026-04-22*
