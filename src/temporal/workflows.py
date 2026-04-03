from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from src.temporal.activities import (
        ProcessMessageInput,
        handle_process_message_failure_activity,
        process_message_activity,
        sync_pinecone_queue_activity,
    )

PROCESS_MESSAGE_RETRY = RetryPolicy(
    maximum_attempts=4,
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
)


@workflow.defn
class ProcessMessageWorkflow:
    @workflow.run
    async def run(self, message_sid: str, from_number: str, body: str) -> str:
        input = ProcessMessageInput(
            message_sid=message_sid, from_number=from_number, body=body
        )
        try:
            return await workflow.execute_activity(
                process_message_activity,
                input,
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=PROCESS_MESSAGE_RETRY,
            )
        except ActivityError:
            await workflow.execute_activity(
                handle_process_message_failure_activity,
                input,
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            raise


@workflow.defn
class SyncPineconeQueueWorkflow:
    @workflow.run
    async def run(self) -> str:
        return await workflow.execute_activity(
            sync_pinecone_queue_activity,
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
