# Temporal Activity Rules

Rules for writing and modifying Temporal activities in the vici project (Python SDK).

## Activity Definition Pattern

```python
from temporalio import activity
from dataclasses import dataclass

@dataclass
class ProcessInput:
    message_id: int
    phone_hash: str

@activity.defn
async def process_message(input: ProcessInput) -> str:
    """Process a single inbound message through the pipeline."""
    # All I/O happens here -- DB, HTTP, file access
    result = await do_work(input)
    return result.status
```

## Core Rules

### 1. Activities MUST be idempotent

Every activity must produce the same result if called multiple times with the same input.

| Pattern | Implementation |
|---------|---------------|
| DB writes | Use `ON CONFLICT` / upsert or check-before-write |
| API calls | Use idempotency keys where available |
| File writes | Write to deterministic path, overwrite is safe |
| Queue operations | Deduplicate by message ID |

### 2. Activities handle ALL side effects

Workflows must never do I/O. Activities are the only place for:
- Database queries and writes
- HTTP/gRPC calls (OpenAI, Pinecone, Twilio)
- File system operations
- Logging with external context
- Metrics emission

### 3. Single input, single output

Use dataclasses for activity inputs and outputs:

```python
@dataclass
class SyncInput:
    batch_size: int = 100

@dataclass
class SyncOutput:
    processed: int
    failed: int

@activity.defn
async def sync_pinecone_queue(input: SyncInput) -> SyncOutput:
    ...
```

### 4. Keep activities focused

One activity = one logical operation. Split large activities:

```
# Bad: one activity does everything
process_and_store_and_notify()

# Good: separate concerns
extract_data()        # GPT classification
store_records()       # DB persistence
sync_to_pinecone()   # Vector store write
notify_user()        # Twilio SMS
```

## Retry Policies

### Default retry (vici convention)

```python
from temporalio.common import RetryPolicy
from datetime import timedelta

DEFAULT_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=60),
    backoff_coefficient=2.0,
    maximum_attempts=4,
)
```

### Non-retryable errors

Some errors should NOT trigger retries:

```python
from temporalio.exceptions import ApplicationError

@activity.defn
async def validate_input(data: str) -> dict:
    if not data:
        raise ApplicationError(
            "Empty input -- permanent failure",
            non_retryable=True,
        )
```

Mark as non-retryable:
- Validation failures (bad input)
- Authentication failures (wrong credentials)
- Not-found errors (resource doesn't exist)
- Business rule violations

### Retry-safe errors (let retry policy handle)

- Network timeouts
- Rate limits (429)
- Temporary service unavailability (503)
- Database connection errors

## Heartbeats

For long-running activities (>30 seconds), use heartbeats:

```python
@activity.defn
async def process_large_batch(input: BatchInput) -> BatchOutput:
    results = []
    for i, item in enumerate(input.items):
        activity.heartbeat(f"Processing item {i}/{len(input.items)}")
        result = await process_item(item)
        results.append(result)
    return BatchOutput(results=results)
```

Set `heartbeat_timeout` on the workflow side:

```python
await workflow.execute_activity(
    process_large_batch,
    batch_input,
    start_to_close_timeout=timedelta(minutes=10),
    heartbeat_timeout=timedelta(seconds=30),
)
```

If no heartbeat received within timeout, Temporal cancels and retries the activity.

## Cancellation Handling

Activities should handle cancellation gracefully:

```python
@activity.defn
async def long_running_task(input: TaskInput) -> TaskOutput:
    try:
        for chunk in input.chunks:
            activity.heartbeat()
            await process_chunk(chunk)
    except asyncio.CancelledError:
        # Clean up resources
        await cleanup()
        raise  # Re-raise to signal cancellation to Temporal
```

## Accessing Shared State (vici pattern)

Activities in vici access the DI graph through FastAPI `app.state`:

```python
# In activities.py
@activity.defn
async def handle_process_message(input: ProcessInput) -> str:
    orchestrator = app.state.pipeline_orchestrator
    result = await orchestrator.run(input.sms_text, input.phone_hash)
    return result.status
```

The `app.state` is populated during FastAPI lifespan startup. Activities access
it as a module-level reference set during worker initialization.

## Testing Activities

Test activities as regular async functions (no Temporal test harness needed):

```python
@pytest.mark.asyncio
async def test_process_message_activity():
    # Mock dependencies
    mock_orchestrator = AsyncMock()
    mock_orchestrator.run.return_value = PipelineResult(status="ok")

    # Set up app state
    app.state.pipeline_orchestrator = mock_orchestrator

    # Call activity directly
    result = await handle_process_message(
        ProcessInput(message_id=1, phone_hash="abc123")
    )

    assert result == "ok"
    mock_orchestrator.run.assert_called_once()
```

For integration tests that need Temporal, use `WorkflowEnvironment.start_local()`.

## Logging in Activities

Use `activity.logger` for structured logging that includes workflow context:

```python
@activity.defn
async def my_activity(input: MyInput) -> MyOutput:
    activity.logger.info(
        "Processing message",
        extra={"message_id": input.message_id},
    )
```

This automatically includes workflow_id, run_id, and activity_id in log context.
