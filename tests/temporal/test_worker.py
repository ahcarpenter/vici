"""Tests for get_temporal_client wiring of TracingInterceptor."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from temporalio.contrib.opentelemetry import TracingInterceptor


@pytest.mark.asyncio
async def test_get_temporal_client_wires_tracing_interceptor():
    """get_temporal_client passes TracingInterceptor to Client.connect."""
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
