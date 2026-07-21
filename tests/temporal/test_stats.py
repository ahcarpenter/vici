"""Tests for Temporal task-queue backlog stats and the gauge poll loop."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog.testing

from src.temporal.stats import get_task_queue_backlog


def _mock_temporal_client(backlogs_by_type: dict[int, int]):
    """Client whose describe_task_queue returns the given per-type backlogs."""
    type_infos = {}
    for queue_type, count in backlogs_by_type.items():
        type_info = MagicMock()
        type_info.stats.approximate_backlog_count = count
        type_infos[queue_type] = type_info
    version_info = MagicMock()
    version_info.types_info = type_infos
    resp = MagicMock()
    resp.versions_info = {"": version_info}

    client = MagicMock()
    client.namespace = "default"
    client.workflow_service.describe_task_queue = AsyncMock(return_value=resp)
    return client


@pytest.mark.asyncio
async def test_backlog_sums_workflow_and_activity_counts():
    client = _mock_temporal_client({1: 3, 2: 4})

    backlog = await get_task_queue_backlog(client, "vici-queue")

    assert backlog == 7
    req = client.workflow_service.describe_task_queue.await_args.args[0]
    assert req.namespace == "default"
    assert req.task_queue.name == "vici-queue"
    assert req.report_stats is True


@pytest.mark.asyncio
async def test_backlog_rpc_error_propagates():
    """Failures propagate — the gauge loop owns degradation."""
    client = MagicMock()
    client.namespace = "default"
    client.workflow_service.describe_task_queue = AsyncMock(
        side_effect=RuntimeError("Temporal down")
    )

    with pytest.raises(RuntimeError):
        await get_task_queue_backlog(client, "vici-queue")


@pytest.mark.asyncio
async def test_gauge_poll_failures_are_independent():
    """A Temporal read failure must not blind the pinecone depth gauge."""
    from src.main import _GaugeHealth, _poll_gauges_once
    from src.metrics import pinecone_sync_queue_depth

    failing_client = MagicMock()
    failing_client.namespace = "default"
    failing_client.workflow_service.describe_task_queue = AsyncMock(
        side_effect=RuntimeError("Temporal down")
    )
    sync_queue_repo = AsyncMock()
    sync_queue_repo.count_pending = AsyncMock(return_value=3)

    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=AsyncMock())
    session_cm.__aexit__ = AsyncMock(return_value=None)
    health = _GaugeHealth()

    with (
        patch(
            "src.main.get_sessionmaker",
            return_value=MagicMock(return_value=session_cm),
        ),
        structlog.testing.capture_logs() as cap,
    ):
        await _poll_gauges_once(failing_client, sync_queue_repo, health)

    assert pinecone_sync_queue_depth._value.get() == 3
    assert health.db_failures == 0
    assert health.temporal_failures == 1
    assert any("temporal_task_queue depth read failed" in e["event"] for e in cap)
