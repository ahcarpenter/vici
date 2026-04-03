from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode
from temporalio.worker import Worker

import src.temporal.activities as _acts
from src.temporal.activities import (
    handle_process_message_failure_activity,
    process_message_activity,
    sync_pinecone_queue_activity,
)
from src.temporal.workflows import ProcessMessageWorkflow, SyncPineconeQueueWorkflow

TASK_QUEUE = "vici-queue"


async def get_temporal_client(address: str) -> Client:
    """Connect to Temporal server at address (e.g. 'localhost:7233')."""
    return await Client.connect(address)


async def run_worker(client: Client, orchestrator, openai_client) -> None:
    """Long-running coroutine. Cancel to stop. Set singletons before worker.run()."""
    _acts._orchestrator = orchestrator
    _acts._openai_client = openai_client

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
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
    try:
        await client.start_workflow(
            SyncPineconeQueueWorkflow.run,
            id="sync-pinecone-queue-cron",
            task_queue=TASK_QUEUE,
            cron_schedule="*/5 * * * *",
        )
    except RPCError as err:
        if err.status == RPCStatusCode.ALREADY_EXISTS:
            pass  # cron workflow already registered
        else:
            raise
