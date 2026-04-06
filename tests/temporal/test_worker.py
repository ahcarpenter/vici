"""Tests for temporal worker: get_temporal_client and start_cron_if_needed."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from temporalio.contrib.opentelemetry import TracingInterceptor
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode


@pytest.mark.asyncio
async def test_get_temporal_client_wires_tracing_interceptor():
    """get_temporal_client wires TracingInterceptor with workflow spans."""
    mock_client = MagicMock()
    with patch(
        "temporalio.client.Client.connect",
        new_callable=AsyncMock,
        return_value=mock_client,
    ) as mock_connect:
        from src.temporal.worker import get_temporal_client

        await get_temporal_client("localhost:7233")

    _, kwargs = mock_connect.call_args
    interceptors = kwargs.get("interceptors", [])
    assert len(interceptors) == 1
    interceptor = interceptors[0]
    assert isinstance(interceptor, TracingInterceptor)
    assert interceptor._always_create_workflow_spans is True


# --- start_cron_if_needed tests ---


@pytest.mark.asyncio
async def test_start_cron_if_needed_success():
    """First-time registration: start_workflow succeeds without error."""
    from src.temporal.worker import start_cron_if_needed

    mock_client = AsyncMock()
    mock_client.start_workflow = AsyncMock(return_value="wf-handle")

    await start_cron_if_needed(mock_client)

    mock_client.start_workflow.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_cron_if_needed_workflow_already_started():
    """WorkflowAlreadyStartedError is silently swallowed (idempotent)."""
    from src.temporal.worker import start_cron_if_needed

    mock_client = AsyncMock()
    mock_client.start_workflow = AsyncMock(
        side_effect=WorkflowAlreadyStartedError("sync-pinecone-queue-cron", "run-id"),
    )

    # Should not raise
    await start_cron_if_needed(mock_client)


@pytest.mark.asyncio
async def test_start_cron_if_needed_rpc_already_exists():
    """RPCError with ALREADY_EXISTS status is silently swallowed (idempotent)."""
    from src.temporal.worker import start_cron_if_needed

    mock_client = AsyncMock()
    rpc_err = RPCError(
        message="workflow already exists",
        status=RPCStatusCode.ALREADY_EXISTS,
        raw_grpc_status=None,
    )
    mock_client.start_workflow = AsyncMock(side_effect=rpc_err)

    # Should not raise
    await start_cron_if_needed(mock_client)


@pytest.mark.asyncio
async def test_start_cron_if_needed_rpc_other_error_reraises():
    """RPCError with non-ALREADY_EXISTS status is re-raised."""
    from src.temporal.worker import start_cron_if_needed

    mock_client = AsyncMock()
    rpc_err = RPCError(
        message="internal server error",
        status=RPCStatusCode.INTERNAL,
        raw_grpc_status=None,
    )
    mock_client.start_workflow = AsyncMock(side_effect=rpc_err)

    with pytest.raises(RPCError) as exc_info:
        await start_cron_if_needed(mock_client)
    assert exc_info.value.status == RPCStatusCode.INTERNAL
