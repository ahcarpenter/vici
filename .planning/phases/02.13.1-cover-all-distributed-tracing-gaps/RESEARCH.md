# Phase 02.13.1: Cover All Distributed Tracing Gaps - Research

**Researched:** 2026-04-03
**Domain:** OpenTelemetry Python SDK, temporalio contrib OTel, FastAPI auto-instrumentation
**Confidence:** HIGH

## Summary

The project already has a solid OTel foundation: `TracerProvider` with `ALWAYS_ON` sampler, OTLP/gRPC exporter, `FastAPIInstrumentor`, `SQLAlchemyInstrumentor`, and `TracingInterceptor` on the Temporal client. The gaps are surgical: one broken trace boundary (FastAPI → Temporal), one missing parent span (PipelineOrchestrator), one uninstrumented handler (WorkerGoalHandler), missing business attributes on the SMS router span, and missing business attributes on workflow spans.

The most critical gap is `src/sms/service.py` `emit_message_received_event()`. Because the Temporal client is shared and the `TracingInterceptor` is wired on the client (not on the worker only), calling `client.start_workflow()` from within the FastAPI request span **will automatically** inject the current OTel context into the Temporal workflow header `_tracer-data` — but only if the active span at call time is valid. Currently `emit_message_received_event()` is called from the router with no span explicitly active beyond the FastAPI auto-instrumented HTTP span, which means the trace context **is present** and will propagate correctly. No manual propagation code is needed.

However, this propagation is fragile: if `emit_message_received_event()` were ever moved outside the FastAPI request context (e.g., called from a background task), the HTTP span would be detached and the trace would break. The defensive pattern — fetching `get_current_span()` and asserting it is valid before the `start_workflow` call — is a useful guard.

**Primary recommendation:** Add `otel_trace.get_current_span().set_attribute(...)` calls to enrich auto-instrumented spans; add a parent span to `PipelineOrchestrator.run()`; add manual spans to `WorkerGoalHandler.handle()`; and add business attributes (`message.sid`, `messaging.message.id`) to the Temporal workflow enrichment points. No custom propagation code is needed — `TracingInterceptor` on the client handles it automatically.

## Project Constraints (from CLAUDE.md)

- Organize code by domain; module-level `tracer = otel_trace.get_tracer(__name__)` is the established pattern
- SOLID principles: apply when three or more instances of the same code exist, or near-term churn expected — do NOT prematurely optimize
- All magic numbers must be constantized (OTel attribute key strings should be in `constants.py` files)
- Apply DRY: five files need similar span-enrichment patterns; a shared helper is justified
- `ruff check --fix src && ruff format src` before committing
- Async routes: only `await` non-blocking I/O; `asyncio.to_thread` / `run_in_threadpool` for blocking

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| opentelemetry-api | >=1.40.0 (project pinned) | Tracer, span, context APIs | Already in pyproject.toml |
| opentelemetry-sdk | >=1.40.0 | TracerProvider, BatchSpanProcessor | Already in pyproject.toml |
| temporalio[opentelemetry] | >=1.24.0 | TracingInterceptor — client+worker OTel bridge | Already wired in worker.py |
| opentelemetry-instrumentation-fastapi | >=0.61b0 | Auto-instruments HTTP spans | Already in main.py |
| opentelemetry-instrumentation-sqlalchemy | >=0.61b0 | Auto-instruments DB spans | Already in main.py |

No new dependencies are required for this phase.

**Existing import pattern (used in job_posting.py and activities.py, must be followed everywhere):**
```python
from opentelemetry import trace as otel_trace
tracer = otel_trace.get_tracer(__name__)
```

## Architecture Patterns

### Pattern 1: Enriching an Auto-Instrumented Span (SMS Router)

FastAPIInstrumentor creates the HTTP span automatically. To add business attributes to it, retrieve the active span and call `set_attribute`. Do NOT start a new span — that would create an unnecessary child.

**Source:** OTel Python SDK docs — `opentelemetry.trace.get_current_span()`

```python
# src/sms/router.py — inside receive_sms(), after extracting form_data
from opentelemetry import trace as otel_trace

span = otel_trace.get_current_span()
span.set_attribute("messaging.message_id", message_sid)
span.set_attribute("messaging.source.phone_hash", hash_phone(from_number))
```

The span is active because FastAPIInstrumentor wraps the route handler. `get_current_span()` returns the correct HTTP span with no extra context management.

### Pattern 2: Adding a Parent Span (PipelineOrchestrator)

`PipelineOrchestrator.run()` is called from within `temporal.process_message` activity, which itself is already wrapped by `RunActivity:process_message_activity` from the TracingInterceptor. The orchestrator span should be a **child** of that activity span — using `start_as_current_span` makes it a child automatically because the TracingInterceptor span is the current span at that point.

```python
# src/pipeline/orchestrator.py
from opentelemetry import trace as otel_trace

tracer = otel_trace.get_tracer(__name__)

async def run(self, ...) -> ExtractionResult:
    with tracer.start_as_current_span("pipeline.orchestrate") as span:
        span.set_attribute("messaging.message_id", message_sid)
        span.set_attribute("messaging.source.phone_hash", phone_hash)
        span.set_attribute("messaging.destination.address", from_number)
        # existing body unchanged
```

### Pattern 3: Adding Handler Spans (WorkerGoalHandler)

Match the style of `JobPostingHandler` and `UnknownMessageHandler` exactly:

```python
# src/pipeline/handlers/worker_goal.py
from opentelemetry import trace as otel_trace

tracer = otel_trace.get_tracer(__name__)

async def handle(self, ctx: PipelineContext) -> None:
    with tracer.start_as_current_span("pipeline.handle_worker_goal") as span:
        span.set_attribute("messaging.message_id", ctx.message_sid)
        span.set_attribute("app.worker_goal.user_id", str(ctx.user_id))
        # existing body unchanged
```

### Pattern 4: Temporal Context Propagation (Confirmed Working — No Code Change Needed)

The `_TracingClientOutboundInterceptor.start_workflow()` (confirmed from source at `/temporalio/contrib/opentelemetry/_interceptor.py` lines 275-287) wraps every `client.start_workflow()` call:

1. Creates a `StartWorkflow:{workflow_type}` client span as a child of the currently active span
2. Calls `_context_to_headers()` which serializes the current OTel context into the Temporal header `_tracer-data` using W3C TraceContext + Baggage propagation
3. On the worker side, `_TracingActivityInboundInterceptor.execute_activity()` extracts `_tracer-data` from headers and restores the span context before executing the activity

**Result:** As long as `client.start_workflow()` is called while the FastAPI HTTP span is active — which it is, since `emit_message_received_event()` is called from inside the route handler — the trace chain is unbroken. No manual `inject()`/`extract()` calls are needed.

**The one real gap:** `emit_message_received_event()` takes `client: Client` as a parameter and does not verify the active span is valid before calling `start_workflow`. Adding a defensive assertion or structured log is advisable but not required for trace continuity.

### Pattern 5: Workflow Span Business Attributes

`TracingWorkflowInboundInterceptor` creates `RunWorkflow:ProcessMessageWorkflow` with only `temporalWorkflowID` and `temporalRunID`. Business attributes can be added inside the workflow `run()` method via `get_current_span()`, but workflows run in Temporal's sandbox — the correct approach is to call `workflow.info()` and use `workflow.logger` for business context, OR to set attributes on the activity span (which runs outside the sandbox). Since activities already get the `RunActivity:*` span from the interceptor, setting attributes in the activity is the right place.

`process_message_activity` already sets `temporal.event` and `temporal.function`. Add `messaging.message_id` and `messaging.source.phone_hash` there.

### Span Name Conventions (from existing code)

| Location | Span Name |
|----------|-----------|
| extraction/service.py | `gpt.classify_and_extract` |
| pipeline/handlers/job_posting.py | `pinecone.upsert` |
| pipeline/handlers/unknown.py | `twilio.send_sms` |
| temporal/activities.py | `temporal.process_message`, `temporal.sync_pinecone_queue` |

Pattern: `{system}.{operation}` or `{system}.{noun}_{verb}`. Follow this for new spans.

### Anti-Patterns to Avoid
- **Starting a new root span in the router:** `tracer.start_as_current_span()` inside `receive_sms` would create a sibling span disconnected from the FastAPIInstrumentor HTTP span. Use `get_current_span().set_attribute()` instead.
- **Manual W3C header injection in `emit_message_received_event`:** The TracingInterceptor already does this. Doing it again would overwrite the propagated context or create a duplicate header.
- **Calling `otel_trace.get_tracer(__name__)` inside a function:** Must be module-level to avoid repeated tracer creation.
- **Using string literals for attribute keys inline:** Violates AGENTS.md "all magic numbers must be constantized" — put OTel attribute key strings in the domain's `constants.py`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Context propagation to Temporal | Manual inject/extract | TracingInterceptor on client | Already handles W3C TraceContext+Baggage serialization into Temporal headers |
| Workflow-level spans | Custom decorator | TracingInterceptor `always_create_workflow_spans=True` | Already wired; creates RunWorkflow, StartActivity, CompleteWorkflow spans automatically |
| HTTP span creation | Manual span in route | FastAPIInstrumentor (already active) | Re-creating spans leads to orphaned children |
| SQL span creation | Manual span in repo | SQLAlchemyInstrumentor (already active) | Already traces every query |

## Common Pitfalls

### Pitfall 1: Span Created Outside Active Context
**What goes wrong:** `tracer.start_as_current_span("foo")` in a method called from a background task or Celery worker has no parent — span appears as a root in Jaeger.
**Why it happens:** OTel context is thread/task-local. `asyncio.create_task()` does NOT inherit the parent context automatically in Python.
**How to avoid:** Use `copy_context()` when creating tasks: `asyncio.create_task(coro(), context=copy_context())`. Not currently an issue in this codebase since orchestration happens in-line.
**Warning signs:** Orphaned root spans in Jaeger for spans you expect to be children.

### Pitfall 2: Setting Attributes After Span Ends
**What goes wrong:** `span.set_attribute(...)` called after the `with` block exits is silently ignored.
**Why it happens:** OTel marks the span as ended; subsequent mutations are no-ops.
**How to avoid:** Set all attributes inside the `with` block, before any `await`.

### Pitfall 3: Temporal Workflow Sandbox Restrictions
**What goes wrong:** Calling `otel_trace.get_current_span()` from inside a `@workflow.defn` method raises a sandbox violation or returns INVALID_SPAN.
**Why it happens:** Temporal replays workflow code deterministically in a restricted sandbox. The TracingInterceptor works around this by serializing span state to carriers and using `extern_functions`.
**How to avoid:** Do NOT call `tracer.start_as_current_span()` inside workflow `run()` methods. Put all business-attribute enrichment in activities (outside the sandbox).

### Pitfall 4: `always_create_workflow_spans=True` and Orphaned Replay Spans
**What goes wrong:** During Temporal replay, `RunWorkflow` spans are created with no parent (the original client span no longer exists). With `always_create_workflow_spans=True`, these appear as extra root spans.
**Why it happens:** The TracingInterceptor skips creating workflow spans on replay when `always_create_workflow_spans=False` (the default). The project sets `True`.
**How to avoid:** This is intentional in the current config — accept the extra replay spans as a known tradeoff, or switch to `False` if they clutter Jaeger. Do not change this in this phase.

### Pitfall 5: Twilio `messaging.destination` Contains Raw Phone Number
**What goes wrong:** `span.set_attribute("messaging.destination", ctx.from_number)` in `UnknownMessageHandler` writes the raw E.164 phone number to span attributes, which may appear in Jaeger UI and exported telemetry.
**Why it happens:** The attribute was added with the raw number rather than the hash.
**How to avoid:** Use `hash_phone(ctx.from_number)` for any PII-adjacent attributes. This is an existing bug to fix during this phase.

## Code Examples

### Enriching the FastAPI SMS Router Span
```python
# src/sms/router.py — Source: OTel Python API docs
from opentelemetry import trace as otel_trace
from src.sms.service import hash_phone

@router.post("/sms")
async def receive_sms(request: Request, gates=Depends(enforce_rate_limit), ...):
    form_data, user = gates
    message_sid = form_data.get("MessageSid", "")
    from_number = form_data.get("From", "")
    body = form_data.get("Body", "")

    span = otel_trace.get_current_span()
    span.set_attribute("messaging.message_id", message_sid)
    span.set_attribute("messaging.source.phone_hash", hash_phone(from_number))
    span.set_attribute("messaging.system", "twilio")
    # ... rest of handler unchanged
```

### PipelineOrchestrator Parent Span
```python
# src/pipeline/orchestrator.py
from opentelemetry import trace as otel_trace

tracer = otel_trace.get_tracer(__name__)

async def run(self, session, sms_text, phone_hash, message_id, user_id, message_sid, from_number):
    with tracer.start_as_current_span("pipeline.orchestrate") as span:
        span.set_attribute("messaging.message_id", message_sid)
        span.set_attribute("messaging.source.phone_hash", phone_hash)
        # ... existing body
```

### WorkerGoalHandler Span (matching JobPostingHandler style)
```python
# src/pipeline/handlers/worker_goal.py
from opentelemetry import trace as otel_trace

tracer = otel_trace.get_tracer(__name__)

async def handle(self, ctx: PipelineContext) -> None:
    with tracer.start_as_current_span("pipeline.handle_worker_goal") as span:
        span.set_attribute("messaging.message_id", ctx.message_sid)
        span.set_attribute("app.work_request.user_id", str(ctx.user_id))
        # ... existing body
```

### process_message_activity Business Attribute Enrichment
```python
# src/temporal/activities.py — inside existing span context
with tracer.start_as_current_span("temporal.process_message") as span:
    span.set_attribute("temporal.event", "message.received")
    span.set_attribute("temporal.function", "process-message")
    span.set_attribute("messaging.message_id", message_sid)      # ADD
    span.set_attribute("messaging.source.phone_hash", phone_hash) # ADD
    # ... existing body
```

### OTel Attribute Key Constants (per AGENTS.md — no magic strings)
```python
# src/pipeline/constants.py (or per-domain constants.py)
OTEL_ATTR_MESSAGE_ID = "messaging.message_id"
OTEL_ATTR_PHONE_HASH = "messaging.source.phone_hash"
OTEL_ATTR_MESSAGING_SYSTEM = "messaging.system"
OTEL_ATTR_WORK_REQUEST_USER_ID = "app.work_request.user_id"
```

## OTel Semantic Conventions

These are the applicable stable/experimental semantic conventions for attributes in this codebase. Source: OpenTelemetry Semantic Conventions spec (semconv).

| Attribute | Convention Namespace | Used In | Notes |
|-----------|---------------------|---------|-------|
| `gen_ai.system` | GenAI | extraction/service.py | Already correct (`"openai"`) |
| `gen_ai.request.model` | GenAI | extraction/service.py | Already correct |
| `messaging.system` | Messaging | unknown.py, router.py | `"twilio"` is correct |
| `messaging.message_id` | Messaging | router.py, activities.py | Maps to MessageSid |
| `messaging.destination.name` | Messaging | unknown.py | Use instead of raw `messaging.destination` |
| `db.system` | Database | job_posting.py | `"pinecone"` is acceptable (non-standard but consistent) |
| `db.operation.name` | Database | job_posting.py | Stable convention uses `db.operation.name` not `db.operation` |
| `temporalWorkflowID` | Temporal (custom) | interceptor | Temporal's own convention, not OTel standard — keep as-is |

**Note on `db.operation`:** The existing attribute in `job_posting.py` uses `db.operation` (deprecated in OTel semconv 1.21+). The current convention is `db.operation.name`. This is a minor cleanup opportunity.

## Additional Gaps Found Beyond the Original List

### Gap 6: `UnknownMessageHandler` — Raw Phone Number in Span Attribute
**File:** `src/pipeline/handlers/unknown.py` line 36
**Current:** `span.set_attribute("messaging.destination", ctx.from_number)` — raw E.164 number
**Fix:** Use `hash_phone(ctx.from_number)` and rename to `messaging.destination.name`

### Gap 7: `temporal/activities.py` `process_message_activity` — Missing Business Attributes on Existing Span
**File:** `src/temporal/activities.py` lines 46-49
**Current:** Only `temporal.event` and `temporal.function` are set; `message_sid` and `phone_hash` are computed in the activity but not attached to the span
**Fix:** Add `messaging.message_id` and `messaging.source.phone_hash` inside the existing `with tracer.start_as_current_span(...)` block

### Gap 8: `job_posting.py` — Deprecated `db.operation` Attribute
**File:** `src/pipeline/handlers/job_posting.py` line 74
**Current:** `span.set_attribute("db.operation", "upsert")` — deprecated key
**Fix:** Change to `span.set_attribute("db.operation.name", "upsert")` per OTel semconv 1.21+

### No Gap: SMS dependencies.py
`validate_twilio_request`, `check_idempotency`, `get_or_create_user`, `enforce_rate_limit` are FastAPI dependency functions executed inside the HTTP span. They do not need dedicated spans — the SQLAlchemy instrumentor already traces their DB calls. Adding spans here would add noise without signal.

### No Gap: `handle_process_message_failure_activity`
This is a failure handler that only logs and increments a Prometheus counter. No tracing needed — failures are already reflected in the parent activity span's error status via the TracingInterceptor.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/ -x -q` |
| Full suite command | `pytest tests/ --cov=src` |

### Phase Requirements → Test Map

Tracing enrichment is not typically unit-tested (OTel spans are side effects with no return value and no DB state). The validation approach for this phase is:

| Behavior | Test Type | Approach |
|----------|-----------|----------|
| `get_current_span().set_attribute()` calls execute without error | Smoke | Existing integration tests pass (span API is no-op when no provider) |
| `pipeline.orchestrate` span is created as child of activity span | Manual | Verify in Jaeger UI after deploying |
| `WorkerGoalHandler` span created | Smoke | Route test that sends a worker_goal message — assert no exception |
| PII not in Twilio destination attribute | Code review | Verify `hash_phone` used in unknown.py fix |

**Automated test gap:** There are no tests that assert specific OTel span attributes. Creating an in-memory span exporter test fixture would be the correct approach if the team wants automated coverage:

```python
# tests/conftest.py — Wave 0 addition
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

@pytest.fixture
def span_exporter():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    otel_trace.set_tracer_provider(provider)
    yield exporter
    exporter.clear()
```

### Wave 0 Gaps
- [ ] `tests/conftest.py` — Add `span_exporter` fixture for OTel attribute assertions (optional but recommended)

## Environment Availability

Step 2.6: SKIPPED — this phase is purely code changes to existing Python source files. No new external dependencies are introduced. All required libraries (opentelemetry-api, opentelemetry-sdk, temporalio) are already in pyproject.toml.

## Sources

### Primary (HIGH confidence)
- `/Users/ahcarpenter/workspace/vici/.claude/worktrees/agent-a8ff27ec/.venv/lib/python3.12/site-packages/temporalio/contrib/opentelemetry/_interceptor.py` — Direct source inspection of `_TracingClientOutboundInterceptor.start_workflow()` (lines 275-287), `_context_to_headers()` (lines 147-157), and `_TracingActivityInboundInterceptor.execute_activity()` (lines 354-369). Confirms automatic injection on `client.start_workflow()`.
- `src/main.py` — Confirmed TracerProvider setup, FastAPIInstrumentor, SQLAlchemyInstrumentor
- `src/temporal/worker.py` — Confirmed `TracingInterceptor(always_create_workflow_spans=True)` on client
- `src/pipeline/handlers/job_posting.py` — Reference implementation for manual span style

### Secondary (MEDIUM confidence)
- OTel Semantic Conventions for messaging (`messaging.*`), GenAI (`gen_ai.*`), database (`db.*`) — standard namespaces used to validate attribute names

## Metadata

**Confidence breakdown:**
- TracingInterceptor propagation behavior: HIGH — read from installed source code directly
- Span enrichment patterns: HIGH — derived from existing working code in the project
- OTel semantic conventions: MEDIUM — based on known stable spec; `db.operation.name` deprecation of `db.operation` is from semconv 1.21+

**Research date:** 2026-04-03
**Valid until:** 2026-07-01 (OTel Python SDK is stable; temporalio interceptor API is stable in 1.x)
