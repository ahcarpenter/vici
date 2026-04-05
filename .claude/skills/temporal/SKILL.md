# Temporal Skill

Temporal workflow orchestration patterns for the vici project (Python SDK).

## Project Context

Vici uses Temporal for durable message processing and background sync jobs.
Code lives in `src/temporal/` with these modules:

| Module | Purpose |
|--------|---------|
| `workflows.py` | ProcessMessageWorkflow, SyncPineconeQueueWorkflow |
| `activities.py` | Pipeline execution, failure handling, Pinecone queue sweep |
| `worker.py` | Client factory (TracingInterceptor), worker startup, cron scheduling |
| `constants.py` | Task queue names, retry policy values |

## Key Patterns in Use

- **ProcessMessageWorkflow**: 4-attempt retry, on_failure activity for dead-letter handling
- **SyncPineconeQueueWorkflow**: Cron-scheduled sweep of PineconeSyncQueue table
- **TracingInterceptor**: OTel distributed tracing wired on Client.connect (worker inherits)
- **RPCError**: Used for cron idempotency checks
- **app.state DI**: Activities access PipelineOrchestrator via FastAPI app.state

## Rules

Detailed implementation rules are in `rules/`:

| Rule File | When to Load |
|-----------|-------------|
| `rules/workflows.md` | Writing or modifying any workflow definition |
| `rules/activities.md` | Writing or modifying any activity, retry policy, or heartbeat |

## SDK Reference

- Package: `temporalio` (Python 3.10+)
- Docs: https://docs.temporal.io/develop/python
- API: https://python.temporal.io/
- Samples: https://github.com/temporalio/samples-python

## Quick Rules

1. **Workflows MUST be deterministic** -- no I/O, no random, no datetime.now()
2. **Activities handle all side effects** -- DB, HTTP, file I/O
3. **Always set timeouts** -- start_to_close_timeout on every activity call
4. **Activities must be idempotent** -- safe to retry without side effects
5. **Use `continue_as_new()`** for workflows with unbounded history
6. **Test with `WorkflowEnvironment`** -- mock activities, assert workflow logic
7. **Wire tracing on Client.connect** -- worker inherits interceptors automatically

## Conventions (vici-specific)

- Task queue names defined in `src/temporal/constants.py`
- All retry policy numeric values constantized (no magic numbers per AGENTS.md)
- Activities access shared state through FastAPI `app.state` DI graph
- Cron workflows use RPCError for idempotency
- OTel TracingInterceptor from `temporalio.contrib.opentelemetry`
