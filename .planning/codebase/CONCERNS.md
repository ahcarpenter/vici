# Codebase Concerns

**Analysis Date:** 2026-04-06

## Tech Debt

**Migration 003 references renamed table `work_request` instead of `work_goal`:**
- Issue: Migration `2026-04-03_normalize_3nf.py` calls `op.drop_constraint("work_request_user_id_fkey", "work_request")` and `op.drop_column("work_request", "user_id")`, but the table was renamed to `work_goal` in a prior refactor. Running `alembic upgrade head` from scratch fails.
- Files: `migrations/versions/2026-04-03_normalize_3nf.py` (lines 21-24)
- Impact: Cold-start deployments (fresh DB) fail. New developer onboarding blocked until manually patched.
- Fix approach: Create a new migration that corrects the table name reference, or amend migration 003 to use `work_goal` (if no production DB has run it yet).

**Pinecone sync SQL joins on dropped `user_id` column:**
- Issue: `sync_pinecone_queue_activity` uses raw SQL `JOIN job j ON j.id = q.job_id ... JOIN "user" u ON u.id = j.user_id`, but migration 003 dropped `job.user_id` (3NF normalization). The correct join path is `job -> message -> user`.
- Files: `src/temporal/activities.py` (lines 108-114)
- Impact: The Pinecone sync cron workflow fails every 5 minutes. Pinecone index never catches up with pending queue rows.
- Fix approach: Rewrite SQL to `JOIN message m ON m.id = j.message_id JOIN "user" u ON u.id = m.user_id`.

**Pinecone sync failure path uses wrong column name `retry_count`:**
- Issue: The failure UPDATE uses `retry_count=retry_count+1` but the `PineconeSyncQueue` model defines the column as `attempts`.
- Files: `src/temporal/activities.py` (line 150)
- Impact: Pinecone sync failures trigger a secondary SQL error, masking the original failure. Failed rows never get their attempt counter incremented.
- Fix approach: Change `retry_count` to `attempts` in the raw SQL UPDATE statement.

**`PineconeSyncQueue.attempts` field vs `last_error` field unused in write path:**
- Issue: The model defines `attempts` and `last_error` fields, but `sync_pinecone_queue_activity` never writes to `last_error`, and the `attempts` column is only updated in the broken SQL path.
- Files: `src/extraction/models.py` (lines 18-19), `src/temporal/activities.py` (lines 147-155)
- Impact: Debugging sync failures requires log analysis; no queryable failure state in DB.
- Fix approach: Update the failure path to set `last_error = :error_msg` and use the correct `attempts` column.

**MatchService not wired into DI graph or WorkerGoalHandler:**
- Issue: `MatchService` exists in `src/matches/service.py` with full DP matching logic, but it is never instantiated in `src/main.py` lifespan and never called from `WorkerGoalHandler`. The worker goal flow ends at DB commit with no matching or SMS reply.
- Files: `src/main.py` (lifespan, lines 122-183), `src/pipeline/handlers/worker_goal.py`, `src/matches/service.py`
- Impact: The core worker-facing feature (text a goal, receive matched jobs) does not function end-to-end.
- Fix approach: Inject `MatchService` and a `TwilioClient` into `WorkerGoalHandler`. After persisting the work goal, call `match_service.match()` then `format_match_sms()` and send via Twilio.

**`format_match_sms()` never called outside tests:**
- Issue: The SMS formatter at `src/matches/formatter.py` is fully implemented and tested, but never imported or called in production code.
- Files: `src/matches/formatter.py`
- Impact: Dead code until MatchService is wired into WorkerGoalHandler.
- Fix approach: Wire into WorkerGoalHandler alongside MatchService integration.

**`temporal_queue_depth` gauge is a permanent stub:**
- Issue: The Prometheus gauge `temporal_queue_depth` always reads 0. Comment states "placeholder for future instrumentation."
- Files: `src/metrics.py` (lines 37-41)
- Impact: Grafana dashboards referencing this metric show meaningless data. No alerting on Temporal queue backlog.
- Fix approach: Use Temporal SDK's `describe_task_queue` API to poll queue depth, or remove the stub gauge.

**Rate limit table UNIQUE constraint migration pending:**
- Issue: The `TODO` comment in `MessageRepository.enforce_rate_limit` notes that a migration to drop the UNIQUE constraint on `(user_id, created_at)` in `rate_limit` is needed. Migration 003 drops it, but the TODO comment remains.
- Files: `src/sms/repository.py` (line 29)
- Impact: Stale TODO; the migration may or may not have run successfully depending on the `work_request` bug. If migration 003 fails mid-way, this constraint may still exist.
- Fix approach: Verify migration 003 succeeds end-to-end, then remove the TODO comment.

**`user_id` not stored on `Job` model after 3NF normalization:**
- Issue: `JobPostingHandler` passes `user_id` to `JobCreate` as a kwarg, but `JobCreate` schema does not have a `user_id` field. Pydantic silently ignores the extra field (no `extra="forbid"`).
- Files: `src/pipeline/handlers/job_posting.py` (line 46), `src/jobs/schemas.py`
- Impact: Silent data loss if `user_id` was intended for use. Currently benign because `user_id` is derivable via `message_id -> message.user_id`.
- Fix approach: Remove `user_id` from `JobCreate` construction call, or add `model_config = ConfigDict(extra="forbid")` to `JobCreate` to catch such issues.

## Known Bugs

**`PipelineContext` claims to be immutable but is a plain `@dataclass`:**
- Symptoms: Nothing prevents mutation of `PipelineContext` fields, despite the docstring saying "Immutable bag of values."
- Files: `src/pipeline/context.py`
- Trigger: Any handler mutating `ctx.session` or `ctx.result` could cause subtle bugs in downstream handlers.
- Workaround: Use `@dataclass(frozen=True)` to enforce immutability.

**`UnknownMessageHandler.handle()` logs `to=ctx.from_number` (raw phone number):**
- Symptoms: PII (raw E.164 phone number) appears in structured logs.
- Files: `src/pipeline/handlers/unknown.py` (line 59)
- Trigger: Any unknown message triggers this log line.
- Workaround: Log `phone_hash` instead of raw `from_number`.

## Security Considerations

**Raw phone number passed through Temporal workflow arguments:**
- Risk: `ProcessMessageWorkflow.run()` receives `from_number` as a plain string argument. Temporal stores workflow inputs in its persistence layer (Postgres). Raw phone numbers are PII stored in a secondary data store.
- Files: `src/temporal/workflows.py` (line 33), `src/sms/service.py` (lines 25-29)
- Current mitigation: Phone numbers are hashed at the application boundary for logging/tracing, but the raw value persists in Temporal's workflow history.
- Recommendations: Pass `phone_hash` through Temporal and resolve `from_number` from DB only when needed (e.g., for Twilio send). Or accept this as a known PII storage location and document it.

**Twilio signature validation skipped in development mode:**
- Risk: When `env == "development"`, `validate_twilio_request` bypasses signature verification entirely.
- Files: `src/sms/dependencies.py` (lines 57-58)
- Current mitigation: Only applies when `ENV=development`. Production uses real validation.
- Recommendations: This is acceptable for local dev, but ensure `ENV` can never be set to `development` in production deployments. Add a startup warning log if `env == "development"`.

**No authentication on `/health`, `/readyz`, or `/metrics` endpoints:**
- Risk: These endpoints are publicly accessible. `/readyz` reveals database connectivity status. `/metrics` exposes Prometheus metrics including GPT call counts, token usage, and queue depths.
- Files: `src/main.py` (lines 202-218, 190)
- Current mitigation: None.
- Recommendations: Restrict `/metrics` to internal network or require a bearer token. Health endpoints are typically fine to expose but `/readyz` should not leak implementation details.

**Grafana default credentials in config:**
- Risk: `grafana_admin_user` and `grafana_admin_password` default to `admin`/`admin` in `Settings`.
- Files: `src/config.py` (lines 75-76)
- Current mitigation: None in code. Depends on `.env` files overriding defaults.
- Recommendations: Remove defaults or raise a warning when default credentials are used in non-development environments.

**No input sanitization on SMS body before GPT processing:**
- Risk: Malicious SMS content is passed directly to the OpenAI API as user input. Prompt injection could cause unexpected GPT behavior.
- Files: `src/extraction/service.py` (line 56), `src/extraction/prompts.py`
- Current mitigation: GPT structured output format (`response_format=ExtractionResult`) constrains the response schema.
- Recommendations: The Pydantic schema validation on `ExtractionResult` provides reasonable defense. Consider adding a max-length check on SMS body before GPT processing.

## Performance Bottlenecks

**DP knapsack algorithm uses O(n * total_earnings) memory:**
- Problem: `_dp_select` allocates arrays proportional to the sum of all candidate earnings in cents. For high-value jobs (e.g., 100 jobs at $1000 each = 10,000,000 capacity), this creates a 10M-element list plus an n x 10M boolean matrix.
- Files: `src/matches/service.py` (lines 102-154)
- Cause: Earnings stored in cents (integer) means the knapsack capacity can be very large.
- Improvement path: Quantize earnings to dollars (divide by 100) for DP computation, or switch to a greedy heuristic for large candidate sets. Add a guard that falls back to greedy when `capacity > THRESHOLD`.

**Pinecone sync processes rows sequentially with individual sessions:**
- Problem: `sync_pinecone_queue_activity` fetches 50 rows but processes each with a separate `get_sessionmaker()()` call for the status update. Each row opens and closes a DB connection.
- Files: `src/temporal/activities.py` (lines 121-155)
- Cause: Error isolation per row, but at the cost of connection overhead.
- Improvement path: Batch successful row IDs and update in a single query. Keep individual error handling but batch the success path.

**Gauge updater polls every 15 seconds with a full COUNT query:**
- Problem: `_update_gauges()` runs `SELECT COUNT(*) FROM pinecone_sync_queue WHERE status = 'pending'` every 15 seconds. On large tables this is a sequential scan.
- Files: `src/main.py` (lines 90-119)
- Cause: No index on `pinecone_sync_queue.status`.
- Improvement path: Add an index on `pinecone_sync_queue(status)` or use a materialized counter.

## Fragile Areas

**Raw SQL strings scattered across the codebase:**
- Files: `src/temporal/activities.py` (lines 107-155), `src/pipeline/handlers/job_posting.py` (lines 62-65, 93-97), `src/pipeline/handlers/worker_goal.py` (lines 46-49), `src/sms/repository.py` (lines 34-50), `src/users/repository.py` (lines 19-27)
- Why fragile: Raw SQL strings are not validated at import time. Schema changes (column renames, table renames) silently break at runtime. Migration 003 already caused breakage in `activities.py` by dropping `job.user_id`.
- Safe modification: Use SQLModel/SQLAlchemy ORM queries where possible. For raw SQL, add integration tests that exercise the exact queries against a test DB.
- Test coverage: The Pinecone sync raw SQL paths have no test coverage. `UPDATE message SET message_type = ...` in handlers has no direct test.

**Handler ordering in `PipelineOrchestrator` is implicit:**
- Files: `src/main.py` (lines 142-157), `src/pipeline/orchestrator.py` (lines 67-70)
- Why fragile: `UnknownMessageHandler.can_handle()` returns `True` unconditionally, so it must be last in the list. Handler order is set by list position in `main.py` lifespan with no enforcement.
- Safe modification: Add a `priority` attribute or ordering mechanism to `MessageHandler`. Add a startup assertion that the catch-all handler is last.
- Test coverage: No test verifies handler ordering or ensures the catch-all is last.

**`_orchestrator` and `_openai_client` module-level singletons in activities:**
- Files: `src/temporal/activities.py` (lines 24-25), `src/temporal/worker.py` (lines 30-31)
- Why fragile: Module-level mutable singletons set by `run_worker()` before worker starts. If worker initialization order changes, activities run with `None` references causing `AttributeError`.
- Safe modification: Add null checks with clear error messages in activity functions.
- Test coverage: Tests mock these at the module level; no test verifies the actual initialization path.

## Scaling Limits

**Single Temporal worker co-located with FastAPI process:**
- Current capacity: One worker task running inside the FastAPI process handles all workflow and activity executions.
- Limit: CPU-bound OpenAI/Pinecone calls in activities block the single worker. Under high SMS volume, the Temporal task queue backs up.
- Scaling path: Run Temporal workers as separate processes/containers. The worker code in `src/temporal/worker.py` is already decoupled enough to extract.

**Rate limiting uses per-row inserts with rolling window COUNT:**
- Current capacity: Adequate for low-to-moderate SMS volume.
- Limit: Each SMS inserts a `rate_limit` row and counts rows in the window. The `rate_limit` table grows unboundedly (no cleanup/TTL).
- Scaling path: Add a periodic cleanup job to delete `rate_limit` rows older than the window. Consider Redis-based rate limiting for higher throughput.

## Dependencies at Risk

**`braintrust` SDK pinned loosely (`>=0.0.100`):**
- Risk: Pre-1.0 SDK with potentially breaking changes on minor version bumps. The `wrap_openai` and `init_logger` APIs could change.
- Files: `pyproject.toml` (line 8), `src/main.py` (line 7), `src/extraction/service.py` (line 35)
- Impact: Broken OpenAI client wrapping or logging on dependency update.
- Migration plan: Pin to a specific version. Monitor release notes.

**`sqlmodel` at `>=0.0.37` (pre-1.0):**
- Risk: SQLModel is a wrapper around SQLAlchemy with its own quirks. Pre-1.0 API may change.
- Files: `pyproject.toml` (line 23), all model files
- Impact: Model definition changes could break on update.
- Migration plan: Pin version. All models use `SQLModel` with `table=True`.

## Missing Critical Features

**No STOP/START opt-out mechanism (SEC-05):**
- Problem: Users cannot opt out of receiving SMS messages. Regulatory compliance (TCPA/10DLC) typically requires STOP keyword handling.
- Blocks: Production launch; potential legal/compliance issues with SMS messaging.

**No job poster confirmation SMS (STR-03):**
- Problem: When a job is successfully posted, the poster receives no confirmation. They have no feedback that their SMS was processed.
- Blocks: User trust and basic UX expectations.

**Worker goal flow does not return matched jobs (ASYNC-02):**
- Problem: Workers can text their earnings goal, but the system stores it and stops. No matching runs, no SMS reply sent.
- Blocks: The primary user-facing value proposition.

## Test Coverage Gaps

**No tests for Pinecone sync cron activity:**
- What's not tested: `sync_pinecone_queue_activity` SQL queries, row processing, error handling, status updates.
- Files: `src/temporal/activities.py` (lines 97-166)
- Risk: Three known bugs exist in this code path (dropped column, wrong column name, missing `last_error` write). All would be caught by basic integration tests.
- Priority: High

**No tests for `_update_gauges` background task:**
- What's not tested: The gauge polling loop, error handling, consecutive failure counting.
- Files: `src/main.py` (lines 90-119)
- Risk: Silent metric staleness if DB connection fails. The `-1` sentinel value on repeated failures is untested.
- Priority: Medium

**No tests for raw SQL UPDATE statements in handlers:**
- What's not tested: `UPDATE message SET message_type = ...` in `JobPostingHandler`, `WorkerGoalHandler`, and `UnknownMessageHandler`.
- Files: `src/pipeline/handlers/job_posting.py` (line 63), `src/pipeline/handlers/worker_goal.py` (line 47), `src/pipeline/handlers/unknown.py` (line 33)
- Risk: Column rename or table change silently breaks these at runtime.
- Priority: Medium

**No tests for `UserRepository.get_or_create` raw SQL upsert:**
- What's not tested: The `INSERT ... ON CONFLICT DO NOTHING` pattern and subsequent SELECT. Uses PostgreSQL-specific syntax but tests run against SQLite.
- Files: `src/users/repository.py` (lines 14-35)
- Risk: Dialect-specific SQL may behave differently in SQLite tests vs PostgreSQL production.
- Priority: Medium

**Worker goal integration test skipped:**
- What's not tested: Full end-to-end worker goal flow through Temporal.
- Files: `tests/integration/test_worker_goal.py`
- Risk: The worker goal path is the least tested critical flow.
- Priority: High

---

*Concerns audit: 2026-04-06*
