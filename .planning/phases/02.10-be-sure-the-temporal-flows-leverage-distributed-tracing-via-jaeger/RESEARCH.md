# Phase 02.10: Temporal Distributed Tracing via Jaeger - Research

**Researched:** 2026-04-03
**Domain:** Temporal Python SDK OpenTelemetry integration (`temporalio.contrib.opentelemetry`)
**Confidence:** HIGH

---

## Summary

The Temporal Python SDK ships `temporalio.contrib.opentelemetry.TracingInterceptor` as a first-party module inside the `temporalio` package — no separate install is needed. Wiring it requires one call site change: passing `interceptors=[TracingInterceptor()]` to `Client.connect()`. Once on the client, the interceptor automatically covers all worker-side spans too (workflows and activities), because the worker inherits the client's interceptors. The interceptor uses the globally-set `otel_trace.get_tracer()` by default, meaning it picks up the `TracerProvider` already configured in `src/main.py` without any additional plumbing.

Trace context propagation from the FastAPI HTTP layer into Temporal works automatically when the OTel `FastAPIInstrumentor` is active and `TracingInterceptor` is on the client, because both live in the same process and share the same OTel context during the `client.start_workflow()` call. The interceptor serializes the active OTel span context into a Temporal header (`_tracer-data`) and deserializes it on the worker side, stitching the workflow/activity spans as children of the originating HTTP span.

One important behavioral default to understand: the Python SDK does **not** create `RunWorkflow` spans unless either a client-side span exists at `start_workflow` time, or `always_create_workflow_spans=True` is passed to `TracingInterceptor`. Since this application starts workflows from within a FastAPI request handler (which is already instrumented by `FastAPIInstrumentor`), a parent HTTP span will exist and `RunWorkflow` spans will be created automatically for `ProcessMessageWorkflow`. The cron workflow (`SyncPineconeQueueWorkflow`) is started at startup with no HTTP parent, so `always_create_workflow_spans=True` is recommended to get workflow-level spans for the cron path.

**Primary recommendation:** Add `interceptors=[TracingInterceptor(always_create_workflow_spans=True)]` to `Client.connect()` in `get_temporal_client()`. No changes to the Worker constructor are needed when the interceptor is on the client.

---

## Project Constraints (from CLAUDE.md)

- Use `ruff check --fix src` and `ruff format src` for linting/formatting.
- Async routes and async activity functions: use only non-blocking I/O.
- SOLID principles only when near-term churn is expected or DRY applies to 3+ instances. Do not over-engineer.
- Project structure: domain-organized under `src/`.
- OTel provider is already configured globally in `src/main.py` — do not create a second provider.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `temporalio` | >=1.24.0 (pinned in pyproject.toml) | Temporal Python SDK including `contrib.opentelemetry` | First-party; contrib module ships inside the package |
| `opentelemetry-api` | >=1.40.0 | OTel API; `get_tracer_provider()` | Already installed |
| `opentelemetry-sdk` | >=1.40.0 | `TracerProvider`, `BatchSpanProcessor` | Already installed |
| `opentelemetry-exporter-otlp` | >=1.40.0 | OTLP gRPC exporter to Jaeger | Already installed |

### No Additional Installs Required

The `temporalio[opentelemetry]` extras group exists but only adds optional dependencies (`opentelemetry-api`, `opentelemetry-sdk`) that are **already present** in `pyproject.toml`. Verify:

```bash
python -c "from temporalio.contrib.opentelemetry import TracingInterceptor; print('OK')"
```

---

## Architecture Patterns

### Recommended Change: Client-Level Interceptor

Wire the interceptor on `Client.connect()` — not on `Worker()`. This covers both sides.

**`src/temporal/worker.py` — `get_temporal_client()`:**

```python
# Source: https://github.com/temporalio/samples-python/blob/main/open_telemetry/worker.py
from temporalio.contrib.opentelemetry import TracingInterceptor

async def get_temporal_client(address: str) -> Client:
    return await Client.connect(
        address,
        interceptors=[TracingInterceptor(always_create_workflow_spans=True)],
    )
```

`run_worker()` and `Worker(...)` require no changes — the worker inherits interceptors from the client.

### Interceptor Placement: Client vs Worker

| Placement | Covers | When to Use |
|-----------|--------|-------------|
| `Client.connect(interceptors=[...])` | Client calls + all workers using that client | Recommended — single call site |
| `Worker(interceptors=[...])` | Worker-side only (activities/workflows), no client spans | Use only if client spans are unwanted |

For this application, client-level placement is correct because the `temporal_client` in `app.state` is used for both starting workflows (from the SMS webhook handler) and running the worker.

### `always_create_workflow_spans=True`

```python
# Source: https://community.temporal.io/t/fix-workflow-level-otlp-tracing-with-python-workers/17255
TracingInterceptor(always_create_workflow_spans=True)
```

Without this flag, the Python SDK only creates a `RunWorkflow` span when the workflow was started with a client-side span present. The cron workflow `SyncPineconeQueueWorkflow` is registered at startup (outside any HTTP request), so it would never get a `RunWorkflow` span without this flag.

### How Context Propagates: HTTP → Temporal

```
FastAPI route (HTTP request arrives)
    └── FastAPIInstrumentor creates HTTP server span (OTel context active)
        └── client.start_workflow(ProcessMessageWorkflow, ...)
            └── TracingInterceptor._context_to_headers():
                    serializes active OTel span context → Temporal header "_tracer-data"
                └── Temporal server stores header in workflow metadata
                    └── Worker picks up task
                        └── TracingInterceptor._context_from_headers():
                                deserializes → restores OTel context as parent
                            └── RunWorkflow:ProcessMessageWorkflow span (child of HTTP span)
                                └── StartActivity:process_message_activity
                                    └── RunActivity:process_message_activity
```

No manual context injection is required. The propagator used is W3C TraceContext + W3C Baggage (OTel defaults).

### Span Naming Convention

The `TracingInterceptor` auto-creates these spans (names confirmed from Temporal community and SDK docs):

| Span Name | Created By | When |
|-----------|-----------|------|
| `StartWorkflow:{WorkflowType}` | Client interceptor | On `client.start_workflow()` |
| `RunWorkflow:{WorkflowType}` | Worker interceptor | Workflow task execution |
| `StartActivity:{activity_fn_name}` | Workflow interceptor | When activity is scheduled |
| `RunActivity:{activity_fn_name}` | Worker interceptor | Activity task execution |

For this codebase:
- `RunWorkflow:ProcessMessageWorkflow`
- `RunActivity:process_message_activity`
- `RunActivity:sync_pinecone_queue_activity`

### Manual Span in `process_message_activity`

The existing `tracer.start_as_current_span("temporal.process_message")` in `process_message_activity` is **complementary, not redundant**. The `TracingInterceptor` creates `RunActivity:process_message_activity` as the outer span; the manual span creates a child span with application-level attributes (`temporal.event`, `temporal.function`). This is the correct pattern for enriching auto-instrumented spans with domain context.

The manual span should be **retained as-is**. It becomes a child of `RunActivity:process_message_activity` once the interceptor is wired, giving a clean hierarchy in Jaeger.

### Adding Spans to `sync_pinecone_queue_activity`

The activity has per-row iteration. Recommended pattern is a lightweight span wrapping the sweep, with per-row events rather than per-row child spans (avoids span explosion for large batches):

```python
# Pattern: single activity span + row-level events
tracer = otel_trace.get_tracer(__name__)

@activity.defn
async def sync_pinecone_queue_activity() -> str:
    with tracer.start_as_current_span("temporal.sync_pinecone_queue") as span:
        # ... existing sweep logic ...
        span.set_attribute("pinecone.rows_processed", len(rows))
        # For failures, use span events instead of child spans:
        span.add_event("row_failed", {"job_id": str(row["job_id"])})
    return "ok"
```

This produces one `temporal.sync_pinecone_queue` span (child of `RunActivity:sync_pinecone_queue_activity`) visible in Jaeger with aggregate metadata.

### Anti-Patterns to Avoid

- **Do not create a second `TracerProvider`** in worker.py. The provider in `src/main.py` is already globally set via `otel_trace.set_tracer_provider(provider)`. `TracingInterceptor()` with no arguments calls `otel_trace.get_tracer()` which uses this provider.
- **Do not pass `TracingInterceptor` to both `Client.connect()` and `Worker()`** — it will double-instrument and create duplicate spans.
- **Do not rely on span duration for in-workflow spans.** OTel requires the span creator process to end the span. Temporal workflows can replay across processes. The interceptor handles this correctly for activities (which run in a single process execution), but for any spans started inside `@workflow.defn` methods, duration is not reliable. Only start spans inside `@activity.defn` functions.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Span context serialization into Temporal headers | Custom header codec | `TracingInterceptor` | Handles W3C propagation, replay safety, binary encoding |
| Parent-child span linking across workflow/activity | Manual context injection | `TracingInterceptor` | Context is lost across task queue boundaries without the interceptor's header mechanism |
| Workflow-safe span IDs | Random UUIDs | `TemporalIdGenerator` (internal to interceptor) | Workflow replay must produce deterministic IDs or Temporal's determinism checker will fail |

**Key insight:** Temporal workflows are deterministic state machines that replay from event history. Any non-deterministic call (including random span ID generation) inside a workflow will cause a non-determinism error. `TracingInterceptor` uses `TemporalIdGenerator` internally to make span IDs deterministic during replay. Hand-rolling trace context injection inside `@workflow.defn` methods will break replay.

---

## Common Pitfalls

### Pitfall 1: Missing `always_create_workflow_spans` for Cron Workflows

**What goes wrong:** `SyncPineconeQueueWorkflow` spans appear in Jaeger only at the activity level (`RunActivity:sync_pinecone_queue_activity`) with no parent `RunWorkflow` span, making traces appear orphaned.

**Why it happens:** The Python SDK default only creates `RunWorkflow` spans when the calling client had an active span at `start_workflow` time. The cron workflow is registered at app startup with no HTTP context.

**How to avoid:** Pass `always_create_workflow_spans=True` to `TracingInterceptor`.

**Warning signs:** Jaeger shows `RunActivity` spans with no parent in the trace graph for the cron workflow.

### Pitfall 2: TracerProvider Not Set Before `Client.connect`

**What goes wrong:** `TracingInterceptor()` captures `otel_trace.get_tracer()` at instantiation time. If it runs before `otel_trace.set_tracer_provider(provider)`, spans go to the no-op tracer.

**Why it happens:** In `src/main.py`, `_configure_otel()` sets the global provider, then `get_temporal_client()` is called. If order changes, the interceptor gets a no-op tracer.

**How to avoid:** `get_temporal_client()` is called inside the `lifespan` function after `_configure_otel(app)`. This ordering is already correct. Document it explicitly so it is not accidentally reordered.

**Warning signs:** No Temporal spans appear in Jaeger despite the interceptor being wired.

### Pitfall 3: Spans Inside `@workflow.defn` Methods

**What goes wrong:** Manual `tracer.start_as_current_span(...)` inside a workflow `run()` method causes non-determinism errors during replay because the span start/end is a side effect.

**Why it happens:** Temporal replays workflow history to rebuild state. Any side effect that differs between original and replay causes a non-determinism exception.

**How to avoid:** Only create manual spans inside `@activity.defn` functions. The existing manual span in `process_message_activity` is correct. Neither workflow currently has manual spans — maintain this.

**Warning signs:** `temporalio.exceptions.WorkflowNondeterminismError` in worker logs.

### Pitfall 4: Double-Registering the Interceptor

**What goes wrong:** Passing `TracingInterceptor` to both `Client.connect()` and `Worker()` produces duplicate spans (two `RunActivity` spans per activity execution).

**Why it happens:** When the client has the interceptor, the worker automatically gets it too. Adding it again at the worker level doubles up.

**How to avoid:** Register only on `Client.connect()`.

---

## Code Examples

### Wire TracingInterceptor (the complete change)

```python
# Source: https://github.com/temporalio/samples-python/blob/main/open_telemetry/worker.py
# File: src/temporal/worker.py

from temporalio.contrib.opentelemetry import TracingInterceptor

async def get_temporal_client(address: str) -> Client:
    """Connect to Temporal server. TracerProvider must be set globally before calling."""
    return await Client.connect(
        address,
        interceptors=[TracingInterceptor(always_create_workflow_spans=True)],
    )
```

### Span for `sync_pinecone_queue_activity`

```python
# File: src/temporal/activities.py
# Pattern: wrap sweep in a single span, use attributes for aggregates

@activity.defn
async def sync_pinecone_queue_activity() -> str:
    logger = structlog.get_logger()
    with tracer.start_as_current_span("temporal.sync_pinecone_queue") as span:
        logger.info("sync-pinecone-queue: starting sweep")
        # ... existing fetch logic ...
        span.set_attribute("pinecone.rows_fetched", len(rows))
        failed = 0
        for row in rows:
            try:
                # ... upsert logic ...
            except Exception as exc:
                failed += 1
                span.add_event("row_upsert_failed", {"job_id": str(row["job_id"])})
        span.set_attribute("pinecone.rows_failed", failed)
    return "ok"
```

### Verify interceptor is active (test pattern)

```python
# The TracingInterceptor picks up the globally-set provider.
# Test by setting an InMemorySpanExporter provider before calling get_temporal_client.
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry import trace as otel_trace

exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
otel_trace.set_tracer_provider(provider)

# Now instantiate TracingInterceptor — it will use this provider
```

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio (asyncio_mode = "auto") |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/temporal/ -x -q` |
| Full suite command | `pytest -x -q` |

### Phase Requirements → Test Map

| Behavior | Test Type | Automated Command | File Exists? |
|----------|-----------|-------------------|-------------|
| `TracingInterceptor` is attached to `Client.connect` | unit | `pytest tests/temporal/test_worker.py -x -q` | Wave 0 |
| `TracingInterceptor` uses the globally-configured provider | unit | `pytest tests/temporal/test_worker.py -x -q` | Wave 0 |
| `RunActivity` span created for `process_message_activity` | integration | manual / sandbox only | N/A |
| Manual `temporal.process_message` span still emitted | unit | `pytest tests/temporal/test_spans.py -x -q` | EXISTS |
| `temporal.sync_pinecone_queue` span emitted | unit | `pytest tests/temporal/test_spans.py -x -q` | Wave 0 (new test case) |
| `always_create_workflow_spans=True` flag present | unit | `pytest tests/temporal/test_worker.py -x -q` | Wave 0 |

### Wave 0 Gaps

- [ ] `tests/temporal/test_worker.py` — verify `get_temporal_client` passes `TracingInterceptor(always_create_workflow_spans=True)` in interceptors
- [ ] New test case in `tests/temporal/test_spans.py` — verify `sync_pinecone_queue_activity` emits `temporal.sync_pinecone_queue` span

**No new framework install needed** — existing pytest + opentelemetry InMemorySpanExporter covers all test cases.

---

## Environment Availability

| Dependency | Required By | Available | Notes |
|------------|------------|-----------|-------|
| `temporalio.contrib.opentelemetry` | TracingInterceptor | Bundled with `temporalio>=1.24.0` | Verify with `python -c "from temporalio.contrib.opentelemetry import TracingInterceptor"` |
| Jaeger (OTLP receiver) | Span export | Runtime service | No code change needed; existing exporter already points to it |

No missing dependencies. `temporalio[opentelemetry]` extras are optional and already satisfied by existing pyproject.toml deps.

---

## Open Questions

1. **`_tracer-data` header key collision with other interceptors**
   - What we know: The header key is `_tracer-data` (SDK default). No other interceptors currently registered.
   - What's unclear: Whether the codebase will add other interceptors in future phases.
   - Recommendation: Proceed with default key. Document it for future phases.

2. **Replay-safe span IDs and `workflow.unsafe.imports_passed_through()`**
   - What we know: `TracingInterceptor` uses an internal `TemporalIdGenerator`. The workflow file already uses `workflow.unsafe.imports_passed_through()` to import from activities.
   - What's unclear: Whether `TracingInterceptor` import in `worker.py` (not in workflow code) triggers any sandbox restrictions.
   - Recommendation: Import `TracingInterceptor` only in `worker.py`, never inside `@workflow.defn` — current architecture already satisfies this.

---

## Sources

### Primary (HIGH confidence)

- [temporalio/samples-python — open_telemetry/worker.py](https://github.com/temporalio/samples-python/tree/main/open_telemetry) — Official Temporal sample showing exact `TracingInterceptor` + `Client.connect` pattern
- [python.temporal.io — TracingInterceptor](https://python.temporal.io/temporalio.contrib.opentelemetry.TracingInterceptor.html) — Official API docs: constructor params, `tracer` defaults to `otel_trace.get_tracer()`, `always_create_workflow_spans`
- [python.temporal.io — contrib.opentelemetry module](https://python.temporal.io/temporalio.contrib.opentelemetry.html) — Module-level docs on interceptor placement

### Secondary (MEDIUM confidence)

- [Temporal Community Forum — Fix Workflow level OTLP tracing with Python workers](https://community.temporal.io/t/fix-workflow-level-otlp-tracing-with-python-workers/17255) — Confirmed `always_create_workflow_spans=True` behavior and when `RunWorkflow` spans appear
- [docs.temporal.io — Python Observability](https://docs.temporal.io/develop/python/observability) — Official docs confirming interceptors apply to both client and worker

### Tertiary (LOW confidence)

- [oneuptime.com — Instrument Temporal.io Workflows with OpenTelemetry (2026-02)](https://oneuptime.com/blog/post/2026-02-06-instrument-temporal-io-workflows-opentelemetry/view) — Third-party article; patterns consistent with official sample

---

## Metadata

**Confidence breakdown:**
- TracingInterceptor API and placement: HIGH — verified against official sample and API docs
- `always_create_workflow_spans` behavior: HIGH — verified against Temporal community forum with SDK author response
- Span names (`RunWorkflow`, `RunActivity`, etc.): MEDIUM — confirmed from multiple sources, not read directly from source code
- HTTP-to-Temporal context propagation: MEDIUM — inferred from shared process + OTel global context mechanism; no official doc explicitly describes this cross-boundary path for Python

**Research date:** 2026-04-03
**Valid until:** 2026-07-03 (stable SDK, 90 days)
