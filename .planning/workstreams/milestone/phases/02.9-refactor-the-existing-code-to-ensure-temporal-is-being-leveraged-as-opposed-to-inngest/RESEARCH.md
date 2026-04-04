# Phase 02.9: Migrate Inngest to Temporal - Research

**Researched:** 2026-04-02
**Domain:** Temporal Python SDK, FastAPI integration, background workflow orchestration
**Confidence:** HIGH

---

## Summary

This phase replaces two Inngest functions (`process_message` and `sync_pinecone_queue`) with Temporal workflows and activities. Temporal is a durable execution platform that stores workflow state in an external server (backed by PostgreSQL), enabling reliable retries, cron scheduling, and failure handling without the dev-server webhook polling model that Inngest uses.

The migration has three structural concerns: (1) defining Temporal workflows and activities to replace the Inngest functions, (2) running a Temporal Worker as an asyncio background task inside the FastAPI lifespan, and (3) adding a `temporalio/auto-setup` service to docker-compose. The existing async SQLAlchemy (asyncpg) patterns are compatible with Temporal async activities but require each activity invocation to use its own session — no session sharing across concurrent activities.

**Primary recommendation:** Replace `src/inngest_client.py` with `src/temporal/` containing one workflow file and one worker entrypoint. Start the worker via `asyncio.create_task` inside the existing lifespan context manager.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| temporalio | 1.24.0 | Temporal Python SDK — client, worker, workflow/activity decorators | Official SDK from Temporal Technologies Inc |

**Installation:**
```bash
uv add temporalio
```

**Version verified:** `pip show temporalio` via PyPI JSON API returns `1.24.0` as of 2026-04-02.

### Supporting (no new packages required)

The existing dependencies (asyncpg, SQLModel, structlog, opentelemetry) are all compatible. No additional packages are needed.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Temporal cron_schedule on workflow start | Temporal Schedules API | Schedules API is more flexible (pause, backfill, update without redeployment) but requires more setup; cron_schedule on `start_workflow` is simpler and sufficient for a single recurring workflow |

---

## Architecture Patterns

### Recommended Project Structure

```
src/
├── temporal/
│   ├── __init__.py
│   ├── worker.py          # Worker factory + run_worker() coroutine
│   ├── workflows.py       # @workflow.defn classes
│   └── activities.py      # @activity.defn functions
├── inngest_client.py      # DELETED after migration
└── main.py                # Lifespan starts worker task, removes inngest.fast_api.serve
```

### Pattern 1: Workflow Definition

**What:** A Python class decorated with `@workflow.defn`; the entry point method is decorated with `@workflow.run`. Workflow code must be deterministic — no direct I/O, no randomness, no datetime.now(). All I/O goes through activities.

**When to use:** One workflow class per logical operation (`ProcessMessageWorkflow`, `SyncPineconeQueueWorkflow`).

```python
# Source: https://docs.temporal.io/develop/python/core-application
from temporalio import workflow
from datetime import timedelta

@workflow.defn
class ProcessMessageWorkflow:
    @workflow.run
    async def run(self, message_sid: str, from_number: str, body: str) -> str:
        return await workflow.execute_activity(
            process_message_activity,
            ProcessMessageInput(message_sid=message_sid, from_number=from_number, body=body),
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=4),  # 1 attempt + 3 retries
        )
```

### Pattern 2: Activity Definition

**What:** A plain async function decorated with `@activity.defn`. Activities are where real I/O lives (DB queries, external HTTP calls). Each activity invocation gets its own resources.

**When to use:** Wrap the body of each Inngest function handler in an activity.

```python
# Source: https://docs.temporal.io/develop/python/core-application
from temporalio import activity
from dataclasses import dataclass

@dataclass
class ProcessMessageInput:
    message_sid: str
    from_number: str
    body: str

@activity.defn
async def process_message_activity(input: ProcessMessageInput) -> str:
    # DB session opened here, not passed in — each activity owns its session
    async with get_sessionmaker()() as session:
        ...
    return "ok"
```

### Pattern 3: Worker Running Inside FastAPI Lifespan

**What:** The Temporal Worker is started as an `asyncio.create_task` inside the existing lifespan context manager, mirroring the existing `_gauge_task` pattern already in the codebase.

**When to use:** When running a single-process deployment (worker and API server co-located). This avoids a separate process and matches the existing architecture.

```python
# Source: https://python.temporal.io/temporalio.worker.Worker.html
# and https://github.com/temporalio/sdk-python
import asyncio
from temporalio.client import Client
from temporalio.worker import Worker

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing DI setup ...

    temporal_client = await Client.connect(settings.temporal_address)  # e.g. "localhost:7233"
    worker = Worker(
        temporal_client,
        task_queue="vici-queue",
        workflows=[ProcessMessageWorkflow, SyncPineconeQueueWorkflow],
        activities=[process_message_activity, sync_pinecone_queue_activity],
    )
    _worker_task = asyncio.create_task(worker.run())

    # Start cron workflow (idempotent — WorkflowAlreadyStartedError is swallowed)
    await _start_cron_if_needed(temporal_client)

    yield

    _worker_task.cancel()
    try:
        await _worker_task
    except asyncio.CancelledError:
        pass
    await worker.shutdown()
```

### Pattern 4: Triggering a Workflow from a FastAPI Route (Fire-and-Forget)

**What:** Replace `client.send(inngest.Event(...))` with `client.start_workflow(...)`. This returns a `WorkflowHandle` immediately without waiting for the workflow to finish.

**When to use:** In `sms/service.py` after saving the message row to DB.

```python
# Source: https://docs.temporal.io/develop/python/temporal-client
handle = await temporal_client.start_workflow(
    ProcessMessageWorkflow.run,
    message_sid,
    from_number,
    body,
    id=f"process-message-{message_sid}",   # idempotent key
    task_queue="vici-queue",
)
```

The client instance should be stored on `app.state` during lifespan and injected via FastAPI dependency.

### Pattern 5: Cron Schedule (Replacing Inngest TriggerCron)

**What:** Temporal supports a cron_schedule string on workflow start. The schedule is stored on the server — not in the worker code. Starting the workflow a second time with the same `id` raises `WorkflowAlreadyStartedError`, so the start call is idempotent.

```python
# Source: https://docs.temporal.io/develop/python/schedules
from temporalio.client import WorkflowAlreadyStartedError

try:
    await temporal_client.start_workflow(
        SyncPineconeQueueWorkflow.run,
        id="sync-pinecone-queue-cron",
        task_queue="vici-queue",
        cron_schedule="*/5 * * * *",
    )
except WorkflowAlreadyStartedError:
    pass  # Already registered on server — expected on restarts
```

### Pattern 6: Retry Policy

**What:** `RetryPolicy` from `temporalio.common` configures per-activity or per-workflow retries.

```python
# Source: https://docs.temporal.io/develop/python/failure-detection
from temporalio.common import RetryPolicy
from datetime import timedelta

retry_policy = RetryPolicy(
    maximum_attempts=4,          # 1 initial + 3 retries (matches current Inngest retries=3)
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=100),
)
```

Pass to `workflow.execute_activity(..., retry_policy=retry_policy)`.

### Pattern 7: Failure Handling (Replacing Inngest on_failure)

**What:** Temporal has no `on_failure` decorator equivalent. The pattern is a `try/except` block in the workflow's `run` method, catching `ActivityError` after retries are exhausted.

```python
# Source: https://docs.temporal.io/develop/python/error-handling
from temporalio.exceptions import ActivityError

@workflow.defn
class ProcessMessageWorkflow:
    @workflow.run
    async def run(self, input: ProcessMessageInput) -> str:
        try:
            return await workflow.execute_activity(
                process_message_activity,
                input,
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(maximum_attempts=4),
            )
        except ActivityError as e:
            # Equivalent of Inngest on_failure — runs after retries exhausted
            await workflow.execute_activity(
                handle_process_message_failure_activity,
                input,
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            raise  # Re-raise to put workflow in Failed state
```

The failure-logging logic from `_handle_process_message_failure` in `inngest_client.py` moves into a small dedicated activity.

### Anti-Patterns to Avoid

- **Workflow code with direct I/O:** Workflow `run` methods must be deterministic. No `await session.execute(...)`, no `requests.get(...)`, no `datetime.now()`. All I/O lives in activities.
- **Sharing async sessions across concurrent activities:** SQLAlchemy's `AsyncSession` must not be shared across concurrent asyncio tasks. Each activity invocation opens its own session via `get_sessionmaker()()`.
- **Blocking calls inside async activities:** `time.sleep()`, synchronous `requests`, synchronous file reads block the worker's event loop. Use `await asyncio.sleep()`, `httpx.AsyncClient`, etc.
- **Module-level singletons injected via globals:** The current `ic._orchestrator = orchestrator` pattern works for Inngest but is fragile in Temporal. Inject dependencies via closure or a module-level initialized variable set during lifespan before the worker starts.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Retry logic with exponential backoff | Custom retry loop | `RetryPolicy` on `execute_activity` | Temporal stores retry state durably; process crashes don't lose retry count |
| Cron scheduling | `asyncio.sleep` loop or APScheduler | `cron_schedule` on `start_workflow` | Server-side schedule survives app restarts |
| Workflow state persistence | Redis/DB state machine | Temporal's event history | Temporal is the state store; no external state needed |
| Idempotency keys | Custom dedup table | Workflow `id` parameter | Same `id` = same workflow execution; Temporal deduplicates |

**Key insight:** Temporal's value is that workflow history is the source of truth. Writing custom retry or scheduling code recreates what Temporal already provides durably.

---

## Runtime State Inventory

Not a rename/refactor phase in the string-replacement sense. However, the following runtime state requires attention during migration:

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data | Inngest function registrations — registered dynamically at `inngest.fast_api.serve()` call time, no persisted state | Code edit — remove serve() call |
| Live service config | Inngest Dev Server (Docker container `inngest` at port 8288) — has no persisted job queue between restarts | Docker compose service removal |
| OS-registered state | None | None |
| Secrets/env vars | `INNGEST_DEV`, `INNGEST_BASE_URL` in `.env` and docker-compose; `INNGEST_APP_URL` in compose | Remove env vars; add `TEMPORAL_ADDRESS` |
| Build artifacts | `inngest` package in pyproject.toml | Remove from dependencies after migration |

Temporal server state (workflow history) is stored in the Temporal PostgreSQL database — a new `temporal` PostgreSQL database or schema separate from the app's `vici` DB. This is provisioned automatically by `temporalio/auto-setup`.

---

## Common Pitfalls

### Pitfall 1: Workflow Code Performing I/O Directly

**What goes wrong:** Developer puts `await session.execute(...)` directly in the `@workflow.run` method. Temporal replays workflow history on each task, which means the I/O runs multiple times, returns different results, and causes non-determinism errors.

**Why it happens:** Workflow methods are `async def` and look identical to normal async functions.

**How to avoid:** All I/O must be in `@activity.defn` functions called via `workflow.execute_activity()`. The workflow orchestrates; activities do the work.

**Warning signs:** `temporalio.exceptions.DeterminismError` in worker logs.

### Pitfall 2: Blocking the Worker Event Loop in Async Activities

**What goes wrong:** Synchronous blocking calls (`time.sleep`, `requests.get`, synchronous SQLAlchemy `session.execute` on a sync engine) inside `async def` activities freeze the entire worker, blocking all other workflow tasks.

**Why it happens:** Temporal async activities share the same asyncio event loop as the worker.

**How to avoid:** Use only async-compatible libraries inside async activities. The existing codebase already uses asyncpg and `await session.execute(...)` correctly. Do not use `run_in_threadpool` inside activities — use sync activities with a ThreadPoolExecutor instead if a blocking call is unavoidable.

**Warning signs:** Worker becomes unresponsive; workflows stop progressing without errors.

### Pitfall 3: Missing activity_executor for Sync Activities

**What goes wrong:** If any activity is a plain `def` (sync), the `Worker` constructor needs an `activity_executor` (`concurrent.futures.ThreadPoolExecutor`). Without it, a runtime error is raised.

**Why it happens:** Sync activities run in the executor, not the event loop. The executor must be provided explicitly.

**How to avoid:** Either make all activities `async def` (preferred given the codebase already uses asyncpg), or always pass `activity_executor` when mixing sync/async activities.

### Pitfall 4: WorkflowAlreadyStartedError on App Restart

**What goes wrong:** App restarts, lifespan runs `start_workflow` for the cron job again. Temporal raises `WorkflowAlreadyStartedError` because the workflow with that ID already exists on the server.

**Why it happens:** Cron workflows are long-lived; the ID persists on the server across app restarts.

**How to avoid:** Catch `WorkflowAlreadyStartedError` and ignore it. This is the expected idempotent behavior.

### Pitfall 5: Temporal Server Not Ready Before Worker Connects

**What goes wrong:** App container starts before Temporal server has finished schema setup (`auto-setup` can take a few seconds). Worker fails to connect with a gRPC error.

**Why it happens:** No `depends_on` health check for Temporal in docker-compose.

**How to avoid:** Add `depends_on: temporal: condition: service_healthy` in docker-compose, with a health check using `temporal-admin-tools` or a simple TCP check on port 7233.

### Pitfall 6: Orchestrator Singleton Not Available in Activities

**What goes wrong:** Activity function references `_orchestrator` before lifespan has set it. Worker starts immediately after `Client.connect()`, and if Temporal has queued tasks from a previous run, they replay before the lifespan finishes DI setup.

**Why it happens:** Temporal replays buffered tasks as soon as the worker connects.

**How to avoid:** Complete all DI setup (including injecting `_orchestrator` into the activities module) before calling `asyncio.create_task(worker.run())`.

---

## Code Examples

### Full Worker Setup Pattern

```python
# Source: https://python.temporal.io/temporalio.worker.Worker.html
import asyncio
from temporalio.client import Client
from temporalio.worker import Worker

async def run_worker(client: Client, orchestrator, openai_client) -> None:
    """Long-running coroutine; cancel to stop."""
    # Inject dependencies before worker starts accepting tasks
    import src.temporal.activities as acts
    acts._orchestrator = orchestrator
    acts._openai_client = openai_client

    worker = Worker(
        client,
        task_queue="vici-queue",
        workflows=[ProcessMessageWorkflow, SyncPineconeQueueWorkflow],
        activities=[process_message_activity, sync_pinecone_queue_activity],
    )
    await worker.run()
```

### Connecting Client in Lifespan

```python
# Source: https://docs.temporal.io/develop/python/temporal-client
temporal_client = await Client.connect(settings.temporal_address)
# settings.temporal_address = "localhost:7233" local, "temporal:7233" in Docker
app.state.temporal_client = temporal_client
```

### Triggering from SMS Service (Replacing client.send)

```python
# Source: https://docs.temporal.io/develop/python/temporal-client
from temporalio.client import Client

async def emit_message_received(client: Client, message_sid: str, from_number: str, body: str) -> None:
    await client.start_workflow(
        ProcessMessageWorkflow.run,
        message_sid,
        from_number,
        body,
        id=f"process-message-{message_sid}",
        task_queue="vici-queue",
    )
```

### RetryPolicy Matching Current Inngest Config

```python
# Source: https://docs.temporal.io/develop/python/failure-detection
from temporalio.common import RetryPolicy
from datetime import timedelta

PROCESS_MESSAGE_RETRY_POLICY = RetryPolicy(
    maximum_attempts=4,  # inngest retries=3 means 4 total attempts
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
)
```

### Docker Compose Service Block

```yaml
# Source: https://hub.docker.com/r/temporalio/auto-setup
# https://github.com/temporalio/samples-server/tree/main/compose
temporal:
  image: temporalio/auto-setup:1.26.2  # pin version; check Docker Hub for latest
  environment:
    - DB=postgres12
    - DB_PORT=5432
    - POSTGRES_USER=${POSTGRES_USER}
    - POSTGRES_PWD=${POSTGRES_PASSWORD}
    - POSTGRES_SEEDS=postgres
  ports:
    - "7233:7233"
  depends_on:
    postgres:
      condition: service_healthy

temporal-ui:
  image: temporalio/ui:latest
  environment:
    - TEMPORAL_ADDRESS=temporal:7233
  ports:
    - "8080:8080"
  depends_on:
    - temporal
```

The app container should add:
```yaml
environment:
  TEMPORAL_ADDRESS: temporal:7233
```

And remove:
```yaml
# DELETE these:
INNGEST_DEV: "1"
INNGEST_BASE_URL: http://inngest:8288
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `temporalio/docker-compose` repo | `temporalio/samples-server/compose` | 2024 | docker-compose repo archived; use samples-server |
| `temporalio/auto-setup` (community concern about deprecation) | Still the recommended local dev image | 2020 community reversal | auto-setup is NOT deprecated; still correct for local dev |
| Inngest cron via `TriggerCron` | Temporal `cron_schedule` on `start_workflow` | N/A | Direct replacement |
| Inngest `on_failure` decorator | `try/except ActivityError` in workflow `run` | N/A | Logic moves into workflow code |

**Deprecated/outdated:**
- `temporalio/docker-compose` GitHub repo: archived. Use `temporalio/samples-server` instead.

---

## Open Questions

1. **Temporal server version pinning**
   - What we know: `temporalio/auto-setup:latest` is available; samples-server shows postgres-backed setup.
   - What's unclear: Current latest tag for `temporalio/auto-setup`. Should be pinned to match SDK version compatibility.
   - Recommendation: Check `hub.docker.com/r/temporalio/auto-setup/tags` before writing docker-compose. SDK 1.24.0 is compatible with server 1.24+.

2. **Namespace configuration**
   - What we know: Default namespace is `default`, created automatically by auto-setup.
   - What's unclear: Whether the project should use a custom namespace or the default.
   - Recommendation: Use `default` namespace for simplicity; add `TEMPORAL_NAMESPACE` env var for future flexibility.

3. **Temporal UI port conflict with potential future services**
   - What we know: Temporal UI defaults to port 8080; the app runs on 8000.
   - What's unclear: Whether 8080 conflicts with any existing dev tooling.
   - Recommendation: Keep UI on 8080 (no conflict detected in current docker-compose).

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker | Temporal server container | Yes | 24.0.2 | — |
| uv | Python dependency management | Yes | 0.10.8 | — |
| temporalio (PyPI) | Temporal SDK | Not yet installed | 1.24.0 available | — |
| Temporal server (Docker) | Worker connection | Not running | Auto-setup image available | — |
| PostgreSQL | Temporal state store | Yes (existing service) | postgres:16 | — |

**Missing dependencies with no fallback:**
- `temporalio` package must be added to pyproject.toml and installed.
- Temporal server Docker service must be added to docker-compose.yml.

**Missing dependencies with fallback:**
- None.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`, `asyncio_mode = "auto"`) |
| Quick run command | `uv run pytest tests/ -x -q` |
| Full suite command | `uv run pytest tests/` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| — | `ProcessMessageWorkflow` invokes activity with correct args | unit | `pytest tests/temporal/test_workflows.py -x` | Wave 0 |
| — | `SyncPineconeQueueWorkflow` runs cron and invokes activity | unit | `pytest tests/temporal/test_workflows.py -x` | Wave 0 |
| — | Activities call DB and orchestrator correctly | unit (mocked) | `pytest tests/temporal/test_activities.py -x` | Wave 0 |
| — | Inngest routes removed from FastAPI app | integration | `pytest tests/test_main.py -x` | Wave 0 |
| — | Worker starts cleanly in lifespan | integration | `pytest tests/test_main.py::test_lifespan -x` | Wave 0 |

### Wave 0 Gaps

- [ ] `tests/temporal/test_workflows.py` — workflow unit tests using `temporalio.testing.WorkflowEnvironment`
- [ ] `tests/temporal/test_activities.py` — activity unit tests with mocked sessionmaker and orchestrator
- [ ] `tests/temporal/__init__.py` — package init

*(Existing `tests/test_main.py` may need updates to remove Inngest assertions.)*

---

## Sources

### Primary (HIGH confidence)

- [Temporal Python SDK PyPI](https://pypi.org/project/temporalio/) — version 1.24.0 confirmed
- [Temporal Python SDK GitHub README](https://github.com/temporalio/sdk-python) — workflow/activity/worker patterns
- [Temporal Python core-application docs](https://docs.temporal.io/develop/python/core-application) — workflow and activity code patterns
- [Temporal Python failure-detection docs](https://docs.temporal.io/develop/python/failure-detection) — RetryPolicy API
- [Temporal Python schedules docs](https://docs.temporal.io/develop/python/schedules) — cron_schedule syntax
- [Temporal Python error-handling docs](https://docs.temporal.io/develop/python/error-handling) — on_failure equivalent
- [Temporal Python client docs](https://docs.temporal.io/develop/python/temporal-client) — start_workflow vs execute_workflow
- [temporalio.worker.Worker API reference](https://python.temporal.io/temporalio.worker.Worker.html) — Worker constructor params
- [temporalio/auto-setup Docker Hub](https://hub.docker.com/r/temporalio/auto-setup) — Docker image details
- [Temporal sync vs async activity guide](https://docs.temporal.io/develop/python/python-sdk-sync-vs-async) — activity restrictions

### Secondary (MEDIUM confidence)

- [Temporal samples-server compose](https://github.com/temporalio/samples-server/tree/main/compose) — current docker-compose examples (docker-compose repo archived)
- [Temporal Community Forum: auto-setup retirement discussion](https://community.temporal.io/t/feedback-request-retiring-temporalio-auto-setup-docker-image/165) — confirmed auto-setup still recommended

### Tertiary (LOW confidence)

- [Alexander Thiemann blog: Using Temporal with Python](https://www.athiemann.net/2023/01/16/temporal.html) — 2023 pattern examples, verify against current SDK

---

## Project Constraints (from CLAUDE.md)

- **Domain-based project structure** — new Temporal code goes in `src/temporal/` domain folder following the `router.py / service.py / ...` pattern. For this phase: `worker.py`, `workflows.py`, `activities.py`.
- **Async routes use `async def` with `await` only** — the Temporal client `await client.start_workflow(...)` is non-blocking; use in `async def` routes correctly.
- **SOLID principles only when near-term churn expected or 3+ instances of same code** — do not over-engineer the Temporal wrappers. Two workflows do not warrant an abstraction layer.
- **ruff for linting** — run `ruff check --fix src && ruff format src` after implementing.
- **pytest with asyncio** — `asyncio_mode = "auto"` already configured; use `temporalio.testing.WorkflowEnvironment` for workflow unit tests.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — version verified via PyPI JSON API
- Architecture: HIGH — patterns from official Temporal Python docs and SDK reference
- Pitfalls: MEDIUM — async/IO pitfalls from official sync-vs-async doc; singleton ordering pitfall from codebase analysis
- Docker config: MEDIUM — auto-setup image confirmed not deprecated; exact version tag requires Docker Hub check at plan time

**Research date:** 2026-04-02
**Valid until:** 2026-05-02 (Temporal SDK minor versions release frequently; re-verify version before writing pyproject.toml)
