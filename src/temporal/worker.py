from typing import TYPE_CHECKING

from openai import AsyncOpenAI
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
    purge_rate_limit_activity,
    sync_pinecone_queue_activity,
)
from src.temporal.constants import (
    CRON_SCHEDULE_RATE_LIMIT_PURGE,
    WORKFLOW_PINECONE_SYNC_ID,
    WORKFLOW_RATE_LIMIT_PURGE_ID,
)
from src.temporal.workflows import (
    ProcessMessageWorkflow,
    PurgeRateLimitWorkflow,
    SyncPineconeQueueWorkflow,
)

if TYPE_CHECKING:
    from src.pipeline.orchestrator import PipelineOrchestrator


async def get_temporal_client(address: str) -> Client:
    """Connect to Temporal server. TracerProvider must be set globally before calling.

    The worker inherits interceptors from the client automatically.
    """
    return await Client.connect(
        address,
        interceptors=[TracingInterceptor(always_create_workflow_spans=True)],
    )


async def start_process_message_workflow(
    client: Client, *, message_sid: str, from_number: str, body: str
) -> None:
    """Fire-and-forget: start ProcessMessageWorkflow for an inbound SMS.

    Reads the task queue from settings so producers and the worker can never
    disagree about which queue is in use.
    """
    settings = get_settings()
    await client.start_workflow(
        ProcessMessageWorkflow.run,
        args=[message_sid, from_number, body],
        id=f"process-message-{message_sid}",
        task_queue=settings.temporal.task_queue,
    )


async def run_worker(
    client: Client, orchestrator: "PipelineOrchestrator", openai_client: AsyncOpenAI
) -> None:
    """Long-running coroutine. Cancel to stop. Set singletons before worker.run()."""
    _acts._orchestrator = orchestrator
    _acts._openai_client = openai_client
    settings = get_settings()

    worker = Worker(
        client,
        task_queue=settings.temporal.task_queue,
        workflows=[
            ProcessMessageWorkflow,
            SyncPineconeQueueWorkflow,
            PurgeRateLimitWorkflow,
        ],
        activities=[
            process_message_activity,
            handle_process_message_failure_activity,
            sync_pinecone_queue_activity,
            purge_rate_limit_activity,
        ],
    )
    await worker.run()


async def _start_cron(client: Client, run, workflow_id: str, schedule: str) -> None:
    """Register one cron workflow. Idempotent on restart."""
    settings = get_settings()
    try:
        await client.start_workflow(
            run,
            id=workflow_id,
            task_queue=settings.temporal.task_queue,
            cron_schedule=schedule,
        )
    except WorkflowAlreadyStartedError:
        pass  # cron workflow already registered
    except RPCError as err:
        if err.status == RPCStatusCode.ALREADY_EXISTS:
            pass  # cron workflow already registered
        else:
            raise


async def start_cron_if_needed(client: Client) -> None:
    """Register all cron workflows. Idempotent on restart."""
    settings = get_settings()
    await _start_cron(
        client,
        SyncPineconeQueueWorkflow.run,
        WORKFLOW_PINECONE_SYNC_ID,
        settings.temporal.cron_schedule_pinecone_sync,
    )
    await _start_cron(
        client,
        PurgeRateLimitWorkflow.run,
        WORKFLOW_RATE_LIMIT_PURGE_ID,
        CRON_SCHEDULE_RATE_LIMIT_PURGE,
    )
