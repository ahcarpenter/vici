from temporalio.client import Client
from temporalio.contrib.opentelemetry import TracingInterceptor
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode
from temporalio.worker import Worker

import src.temporal.activities as _acts
from src.config import get_settings
from src.temporal.activities import (
    handle_process_message_failure_activity,
    process_message_activity,
    sync_pinecone_queue_activity,
)
from src.temporal.workflows import ProcessMessageWorkflow, SyncPineconeQueueWorkflow


async def get_temporal_client(address: str) -> Client:
    """Connect to Temporal server. TracerProvider must be set globally before calling.

    The worker inherits interceptors from the client automatically.
    """
    return await Client.connect(
        address,
        interceptors=[TracingInterceptor(always_create_workflow_spans=True)],
    )


async def run_worker(client: Client, orchestrator, openai_client) -> None:
    """Long-running coroutine. Cancel to stop. Set singletons before worker.run()."""
    _acts._orchestrator = orchestrator
    _acts._openai_client = openai_client
    settings = get_settings()

    worker = Worker(
        client,
        task_queue=settings.temporal.task_queue,
        workflows=[ProcessMessageWorkflow, SyncPineconeQueueWorkflow],
        activities=[
            process_message_activity,
            handle_process_message_failure_activity,
            sync_pinecone_queue_activity,
        ],
    )
    await worker.run()


async def start_cron_if_needed(client: Client) -> None:
    """Register the Pinecone sync cron workflow. Idempotent on restart."""
    settings = get_settings()
    try:
        await client.start_workflow(
            SyncPineconeQueueWorkflow.run,
            id="sync-pinecone-queue-cron",
            task_queue=settings.temporal.task_queue,
            cron_schedule=settings.temporal.cron_schedule_pinecone_sync,
        )
    except (WorkflowAlreadyStartedError, RPCError) as err:
        already_exists = err.status == RPCStatusCode.ALREADY_EXISTS
        if isinstance(err, WorkflowAlreadyStartedError) or already_exists:
            pass  # cron workflow already registered
        else:
            raise
