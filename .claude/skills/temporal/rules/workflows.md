# Temporal Workflow Rules

Rules for writing and modifying Temporal workflows in the vici project (Python SDK).

## Determinism Constraints

Workflow code MUST be deterministic. The following are FORBIDDEN inside workflow methods:

| Forbidden | Alternative |
|-----------|------------|
| `datetime.now()` | `workflow.now()` |
| `random.random()` | Use activity or `workflow.random()` |
| `uuid.uuid4()` | `workflow.uuid4()` |
| `time.sleep()` | `await asyncio.sleep()` (Temporal-aware) |
| `asyncio.sleep()` | `await workflow.sleep()` (preferred) |
| Any I/O (HTTP, DB, file) | Move to an activity |
| Threading/multiprocessing | Use activities or child workflows |
| Global mutable state | Use workflow instance state |

Reference: https://docs.temporal.io/workflows#deterministic-constraints

## Workflow Definition Pattern

```python
from temporalio import workflow
from temporalio.common import RetryPolicy
from datetime import timedelta

@workflow.defn
class MyWorkflow:
    @workflow.run
    async def run(self, input: MyInput) -> MyOutput:
        result = await workflow.execute_activity(
            my_activity,
            input.data,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=60),
                backoff_coefficient=2.0,
                maximum_attempts=4,
            ),
        )
        return MyOutput(value=result)
```

## Timeout Rules

ALWAYS set these timeouts on activity execution:

| Timeout | Required | Purpose |
|---------|----------|---------|
| `start_to_close_timeout` | YES | Max time for a single activity attempt |
| `schedule_to_close_timeout` | Recommended | Max time including all retries |
| `heartbeat_timeout` | For long activities | Detect stuck activities |

Never omit `start_to_close_timeout` -- Temporal requires at least one timeout.

## Signals and Queries

```python
@workflow.defn
class MyWorkflow:
    def __init__(self):
        self._status = "pending"

    @workflow.signal
    async def update_status(self, new_status: str) -> None:
        self._status = new_status

    @workflow.query
    def get_status(self) -> str:
        return self._status

    @workflow.run
    async def run(self) -> str:
        await workflow.wait_condition(lambda: self._status == "approved")
        return "done"
```

- Signals: async, can mutate state, fire-and-forget from caller
- Queries: sync, read-only, must not mutate state or block

## Child Workflows

Use child workflows when:
- Logic is independently reusable
- You need separate retry/timeout policies
- The sub-process has its own lifecycle

```python
result = await workflow.execute_child_workflow(
    ChildWorkflow.run,
    child_input,
    id=f"child-{workflow.info().workflow_id}-{item_id}",
)
```

## Continue-As-New

For workflows that accumulate unbounded history (loops, cron-like):

```python
@workflow.defn
class PollingWorkflow:
    @workflow.run
    async def run(self, state: PollingState) -> None:
        # Do work...
        new_state = PollingState(iteration=state.iteration + 1)
        workflow.continue_as_new(new_state)
```

Use when event history could exceed ~10K events.

## Cron Workflows (vici pattern)

Vici uses cron schedules for periodic tasks (e.g., SyncPineconeQueueWorkflow):

```python
# In worker.py -- schedule cron workflow
await client.start_workflow(
    SyncPineconeQueueWorkflow.run,
    id="sync-pinecone-queue",
    task_queue=TASK_QUEUE,
    cron_schedule="*/5 * * * *",
)
```

Use `RPCError` with `ALREADY_EXISTS` to handle idempotent cron registration.

## Versioning

When modifying workflow logic that has running executions:

```python
if workflow.patched("my-change-id"):
    # New logic
    await workflow.execute_activity(new_activity, ...)
else:
    # Old logic (for in-flight workflows)
    await workflow.execute_activity(old_activity, ...)
```

After all old workflows complete, use `workflow.deprecate_patch("my-change-id")`.

## Testing

```python
import pytest
from temporalio.testing import WorkflowEnvironment

@pytest.mark.asyncio
async def test_my_workflow():
    async with await WorkflowEnvironment.start_local() as env:
        # Register workflow and mock activities
        async with Worker(
            env.client,
            task_queue="test-queue",
            workflows=[MyWorkflow],
            activities=[mock_activity],
        ):
            result = await env.client.execute_workflow(
                MyWorkflow.run,
                MyInput(data="test"),
                id="test-wf-1",
                task_queue="test-queue",
            )
            assert result.value == "expected"
```

## Error Handling

- `ApplicationError`: Raise for business logic failures (non-retryable by default)
- `ApplicationError(non_retryable=True)`: Skip retries, fail immediately
- Activity exceptions trigger retry policy automatically
- Use `except ActivityError` in workflow to catch activity failures after all retries exhausted
