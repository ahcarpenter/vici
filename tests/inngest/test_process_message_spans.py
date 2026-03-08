"""
Tests for OTel span emission in inngest_client.py process_message handler.
Uses InMemorySpanExporter to capture spans without a real OTLP backend.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


@pytest.fixture
def span_exporter():
    """Set up an InMemorySpanExporter, patching the module-level tracer directly."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    test_tracer = provider.get_tracer("test")

    import src.inngest_client as ic_module
    original_tracer = ic_module.tracer
    ic_module.tracer = test_tracer

    yield exporter

    ic_module.tracer = original_tracer
    exporter.shutdown()


def _make_ctx(message_sid="SMtest123", from_number="+15551234567", body="Need a mover"):
    """Build a minimal mock inngest.Context."""
    ctx = MagicMock()
    ctx.event.data = {
        "message_sid": message_sid,
        "from_number": from_number,
        "body": body,
    }
    return ctx


@pytest.mark.asyncio
async def test_process_message_emits_inngest_span(span_exporter):
    """process_message handler emits a span named 'inngest.process_message' with correct attributes."""
    from src.inngest_client import process_message

    ctx = _make_ctx()

    mock_message = MagicMock()
    mock_message.id = 1
    mock_message.user_id = 10

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_row = MagicMock()
    mock_row.scalar_one_or_none.return_value = mock_message
    mock_session.execute = AsyncMock(return_value=mock_row)

    mock_orchestrator = AsyncMock()
    mock_orchestrator.run = AsyncMock()

    mock_sessionmaker = MagicMock(return_value=mock_session)

    with (
        patch("src.inngest_client.get_sessionmaker", return_value=mock_sessionmaker),
        patch("src.inngest_client._orchestrator", mock_orchestrator),
        patch("src.inngest_client.hash_phone", return_value="hashed"),
    ):
        await process_message._handler(ctx)

    spans = span_exporter.get_finished_spans()
    span_names = [s.name for s in spans]
    assert "inngest.process_message" in span_names, f"Expected span not found. Got: {span_names}"

    inngest_span = next(s for s in spans if s.name == "inngest.process_message")
    attrs = dict(inngest_span.attributes)
    assert attrs.get("inngest.event") == "message.received"
    assert attrs.get("inngest.function") == "process-message"


@pytest.mark.asyncio
async def test_process_message_span_not_emitted_when_message_missing(span_exporter):
    """Handler returns early when message row not found; span still wraps the handler call."""
    from src.inngest_client import process_message

    ctx = _make_ctx(message_sid="SMnotfound")

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_row = MagicMock()
    mock_row.scalar_one_or_none.return_value = None  # message not found
    mock_session.execute = AsyncMock(return_value=mock_row)

    mock_sessionmaker = MagicMock(return_value=mock_session)

    with (
        patch("src.inngest_client.get_sessionmaker", return_value=mock_sessionmaker),
        patch("src.inngest_client.hash_phone", return_value="hashed"),
    ):
        await process_message._handler(ctx)

    # The span should still be present (handler returns "ok" within the span)
    spans = span_exporter.get_finished_spans()
    span_names = [s.name for s in spans]
    assert "inngest.process_message" in span_names
