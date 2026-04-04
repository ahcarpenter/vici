---
phase: 01-infrastructure-foundation
plan: 03
subsystem: infra
tags: [opentelemetry, structlog, prometheus, inngest, fastapi, observability]

requires:
  - phase: 01-01
    provides: FastAPI app skeleton, SQLAlchemy engine, database models
  - phase: 01-02
    provides: webhook route with security gates, sms service functions

provides:
  - OTel TracerProvider initialized in FastAPI lifespan with OTLP gRPC exporter
  - structlog configured with _add_otel_context processor injecting trace_id/span_id
  - Prometheus /metrics endpoint via prometheus-fastapi-instrumentator
  - Inngest client (module-level) + process-message stub at POST /api/inngest
  - emit_message_received_event: injects W3C traceparent, fires message.received event
  - POST /webhook/sms calls emit_message_received_event fire-and-forget

affects: [phase-02, phase-03, phase-04, all phases using trace context]

tech-stack:
  added:
    - opentelemetry-sdk (TracerProvider, BatchSpanProcessor)
    - opentelemetry-exporter-otlp-proto-grpc (OTLPSpanExporter)
    - opentelemetry-instrumentation-fastapi (FastAPIInstrumentor)
    - opentelemetry-instrumentation-sqlalchemy (SQLAlchemyInstrumentor)
    - structlog (JSONRenderer with OTel processor)
    - prometheus-fastapi-instrumentator (Instrumentator)
    - inngest (Inngest client + fast_api.serve)
  patterns:
    - OTel TracerProvider initialized in FastAPI lifespan, not at module level
    - structlog processor chain: add_log_level -> add_logger_name -> otel_context -> timestamp -> JSON
    - inngest_client at module level; imported lazily in route handler to avoid circular import
    - autouse fixture in conftest patches inngest_client.send to prevent real HTTP calls in all tests

key-files:
  created: []
  modified:
    - src/main.py
    - src/sms/service.py
    - src/sms/router.py
    - tests/conftest.py
    - tests/test_health.py
    - tests/test_logging.py
    - tests/sms/test_webhook.py

key-decisions:
  - "inngest_client uses is_production=not settings.inngest_dev — dev mode set via INNGEST_DEV=1 in .env"
  - "SQLAlchemyInstrumentor uses engine.sync_engine — async engine wraps sync engine, instrumentation requires sync reference"
  - "Lazy import of inngest_client inside route handler body breaks circular import: router.py <- main.py <- router.py"
  - "autouse _auto_mock_inngest_send fixture prevents real Inngest HTTP calls from corrupting async event loop in tests"

patterns-established:
  - "OTel init pattern: Resource -> OTLPSpanExporter -> TracerProvider -> BatchSpanProcessor -> instrument_app"
  - "structlog add_otel_context: get_current_span() -> format trace_id as 32-char hex -> inject into event_dict"
  - "Inngest event emission: otel_inject(carrier) -> inngest_client.send(Event(name, data={..., otel: carrier}))"

requirements-completed: [OBS-02, OBS-03, OBS-04, ASYNC-01, ASYNC-03]

duration: 20min
completed: 2026-03-06
---

# Phase 01 Plan 03: Observability Stack + Inngest Wiring Summary

**OTel TracerProvider + structlog JSON logging with trace_id injection + Prometheus /metrics + Inngest client wired into FastAPI lifespan, with message.received event emission from webhook route**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-03-06T09:40:00Z
- **Completed:** 2026-03-06T10:00:00Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments

- FastAPI lifespan now initializes full observability stack: OTel TracerProvider (OTLP gRPC exporter to Jaeger), FastAPI + SQLAlchemy auto-instrumentation, structlog with trace_id/span_id injection, Prometheus /metrics endpoint
- `emit_message_received_event` in service.py injects W3C traceparent carrier and fires Inngest `message.received` event — webhook route now calls it after write_audit_log
- All 11 tests pass with 0 skipped; test_metrics_endpoint, test_trace_id_in_log, and test_inngest_event_emitted all green

## Task Commits

1. **Task 1: Production code — OTel + structlog + Prometheus + Inngest** - `69e60e5` (feat)
2. **Task 2: Tests — un-skip and implement all three observability tests** - `bdbf1f0` (feat)

## Files Created/Modified

- `src/main.py` - Full rewrite: inngest_client, process-message stub, _add_otel_context, _configure_otel, _configure_structlog, lifespan, Prometheus, Inngest serve
- `src/sms/service.py` - Added emit_message_received_event (async, OTel traceparent injection)
- `src/sms/router.py` - Added lazy import of inngest_client + await emit_message_received_event call
- `tests/conftest.py` - Added autouse _auto_mock_inngest_send fixture
- `tests/test_health.py` - Un-skipped and implemented test_metrics_endpoint
- `tests/test_logging.py` - Implemented test_trace_id_in_log (was stub)
- `tests/sms/test_webhook.py` - Un-skipped and implemented test_inngest_event_emitted

## Decisions Made

- `is_production=not settings.inngest_dev` on Inngest client: when `INNGEST_DEV=1` in env, skips signing key requirement
- `engine.sync_engine` passed to SQLAlchemyInstrumentor: the async engine wraps a sync engine internally; the instrumentation library requires the sync reference
- Lazy import of `inngest_client` inside route handler (not at module level): breaks the `router.py -> main.py -> router.py` circular import at load time
- `autouse` fixture `_auto_mock_inngest_send` in conftest: tests that don't mock Inngest explicitly were triggering real HTTP calls to the Inngest dev server, causing async event loop corruption

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Pre-existing tests failing due to inngest_client.send real HTTP calls**
- **Found during:** Task 1 verification
- **Issue:** Adding `emit_message_received_event` call to the webhook route caused `test_idempotency`, `test_audit_row_created`, and `test_phone_created_at` to fail with `RuntimeError: Event loop is closed` — the Inngest SDK's internal aiohttp client made real HTTP calls to the (non-running) Inngest server, corrupting the async event loop
- **Fix:** Added `_auto_mock_inngest_send` autouse fixture to conftest.py patching `src.main.inngest_client.send` globally; tests that explicitly test Inngest use the `mock_inngest_client` fixture which overrides the autouse patch
- **Files modified:** tests/conftest.py
- **Verification:** All 11 tests pass, 0 skipped
- **Committed in:** 69e60e5 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Auto-fix essential for test suite correctness. The autouse mock pattern is idiomatic for preventing real external calls in unit tests.

## Issues Encountered

- Inngest `fast_api.serve()` raises `SigningKeyMissingError` when `is_production=True` and no signing key provided. Fixed by deriving `is_production` from `settings.inngest_dev` — `.env` sets `INNGEST_DEV=1` for local development.

## Next Phase Readiness

- Full observability stack ready: every request produces structured JSON logs with trace_id, Prometheus metrics at /metrics, OTel spans exported to Jaeger (when running via docker compose)
- Inngest event emission working end-to-end — Phase 4 can implement `process-message` function body
- All Phase 1 requirements complete (OBS-02, OBS-03, OBS-04, ASYNC-01, ASYNC-03)

---
*Phase: 01-infrastructure-foundation*
*Completed: 2026-03-06*
