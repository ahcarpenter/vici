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
    from src.temporal.constants import (
        FAILURE_ACTIVITY_TIMEOUT,
        PINECONE_SYNC_ACTIVITY_TIMEOUT,
        PROCESS_MSG_ACTIVITY_TIMEOUT,
        PROCESS_MSG_RETRY_BACKOFF_COEFFICIENT,
        PROCESS_MSG_RETRY_INITIAL_INTERVAL,
        PROCESS_MSG_RETRY_MAX_ATTEMPTS,
        PROCESS_MSG_RETRY_MAX_INTERVAL,
    )

PROCESS_MESSAGE_RETRY = RetryPolicy(
    maximum_attempts=PROCESS_MSG_RETRY_MAX_ATTEMPTS,
    initial_interval=PROCESS_MSG_RETRY_INITIAL_INTERVAL,
    backoff_coefficient=PROCESS_MSG_RETRY_BACKOFF_COEFFICIENT,
    maximum_interval=PROCESS_MSG_RETRY_MAX_INTERVAL,
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
                start_to_close_timeout=PROCESS_MSG_ACTIVITY_TIMEOUT,
                retry_policy=PROCESS_MESSAGE_RETRY,
            )
        except ActivityError:
            await workflow.execute_activity(
                handle_process_message_failure_activity,
                input,
                start_to_close_timeout=FAILURE_ACTIVITY_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            raise


@workflow.defn
class SyncPineconeQueueWorkflow:
    @workflow.run
    async def run(self) -> str:
        return await workflow.execute_activity(
            sync_pinecone_queue_activity,
            start_to_close_timeout=PINECONE_SYNC_ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
