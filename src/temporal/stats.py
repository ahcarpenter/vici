"""Temporal task-queue statistics via the raw workflow service."""

from temporalio.api.enums.v1 import DescribeTaskQueueMode, TaskQueueType
from temporalio.api.taskqueue.v1 import TaskQueue, TaskQueueVersionSelection
from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
from temporalio.client import Client


async def get_task_queue_backlog(client: Client, task_queue: str) -> int:
    """Approximate backlog (workflow + activity tasks) for a task queue.

    Uses the enhanced DescribeTaskQueue mode and sums
    approximate_backlog_count across all build ids and task-queue types.
    Raises on RPC failure — the caller owns degradation.
    """
    resp = await client.workflow_service.describe_task_queue(
        DescribeTaskQueueRequest(
            namespace=client.namespace,
            task_queue=TaskQueue(name=task_queue),
            api_mode=DescribeTaskQueueMode.DESCRIBE_TASK_QUEUE_MODE_ENHANCED,
            versions=TaskQueueVersionSelection(unversioned=True),
            task_queue_types=[
                TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW,
                TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY,
            ],
            report_stats=True,
        )
    )
    return sum(
        type_info.stats.approximate_backlog_count
        for version_info in resp.versions_info.values()
        for type_info in version_info.types_info.values()
    )
