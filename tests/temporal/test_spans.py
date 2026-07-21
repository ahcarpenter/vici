"""Tests for OTel span emission in temporal activities."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.extraction.models import PineconeSyncQueue
from src.temporal.activities import ProcessMessageInput


@pytest.fixture
def span_exporter():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    test_tracer = provider.get_tracer("test")

    import src.temporal.activities as acts_module

    original_tracer = acts_module.tracer
    acts_module.tracer = test_tracer

    yield exporter

    acts_module.tracer = original_tracer
    exporter.shutdown()


def _sessionmaker_over(session):
    class _NonClosing:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return None

    return MagicMock(side_effect=lambda: _NonClosing())


@pytest_asyncio.fixture
async def make_pending_entry(async_session, make_job):
    async def _factory(**job_kwargs) -> PineconeSyncQueue:
        job = await make_job(**job_kwargs)
        entry = PineconeSyncQueue(job_id=job.id)
        async_session.add(entry)
        await async_session.flush()
        return entry

    return _factory


@pytest.mark.asyncio
async def test_process_message_emits_temporal_span(span_exporter):
    """Activity emits a span named temporal.process_message."""
    from src.temporal.activities import process_message_activity

    inp = ProcessMessageInput(
        message_sid="SMtest123",
        from_number="+15551234567",
        body="Need a mover",
    )

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
        patch(
            "src.temporal.activities.get_sessionmaker",
            return_value=mock_sessionmaker,
        ),
        patch("src.temporal.activities._orchestrator", mock_orchestrator),
        patch("src.temporal.activities.hash_phone", return_value="hashed"),
    ):
        await process_message_activity(inp)

    spans = span_exporter.get_finished_spans()
    span_names = [s.name for s in spans]
    assert "temporal.process_message" in span_names

    temporal_span = next(s for s in spans if s.name == "temporal.process_message")
    from src.observability import OTEL_ATTR_MESSAGE_ID, OTEL_ATTR_PHONE_HASH

    attrs = dict(temporal_span.attributes)
    assert attrs.get("temporal.event") == "message.received"
    assert attrs.get("temporal.function") == "process-message"
    assert attrs.get(OTEL_ATTR_MESSAGE_ID) == "SMtest123"
    assert attrs.get(OTEL_ATTR_PHONE_HASH) == "hashed"


@pytest.mark.asyncio
async def test_sync_pinecone_queue_emits_span(
    span_exporter, async_session, make_pending_entry
):
    """Activity emits span named temporal.sync_pinecone_queue with row attributes."""
    import src.temporal.activities as acts
    from src.temporal.activities import sync_pinecone_queue_activity

    await make_pending_entry(description="Mover needed")

    original_openai = acts._openai_client
    acts._openai_client = MagicMock()
    try:
        with (
            patch(
                "src.temporal.activities.get_sessionmaker",
                return_value=_sessionmaker_over(async_session),
            ),
            patch(
                "src.temporal.activities.write_job_embedding",
                AsyncMock(return_value=None),
            ),
            patch("src.temporal.activities.get_settings", return_value=MagicMock()),
        ):
            await sync_pinecone_queue_activity()
    finally:
        acts._openai_client = original_openai

    spans = span_exporter.get_finished_spans()
    span_names = [s.name for s in spans]
    assert "temporal.sync_pinecone_queue" in span_names

    sync_span = next(s for s in spans if s.name == "temporal.sync_pinecone_queue")
    attrs = dict(sync_span.attributes)
    assert attrs.get("pinecone.rows_fetched") == 1
    assert attrs.get("pinecone.rows_failed") == 0


@pytest.mark.asyncio
async def test_sync_pinecone_queue_span_records_failure_event(
    span_exporter, async_session, make_pending_entry
):
    """Failed row adds row_upsert_failed event to span."""
    import src.temporal.activities as acts
    from src.temporal.activities import sync_pinecone_queue_activity

    entry = await make_pending_entry()

    original_openai = acts._openai_client
    acts._openai_client = MagicMock()
    try:
        with (
            patch(
                "src.temporal.activities.get_sessionmaker",
                return_value=_sessionmaker_over(async_session),
            ),
            patch(
                "src.temporal.activities.write_job_embedding",
                AsyncMock(side_effect=Exception("timeout")),
            ),
            patch("src.temporal.activities.get_settings", return_value=MagicMock()),
        ):
            await sync_pinecone_queue_activity()
    finally:
        acts._openai_client = original_openai

    spans = span_exporter.get_finished_spans()
    sync_span = next(s for s in spans if s.name == "temporal.sync_pinecone_queue")
    attrs = dict(sync_span.attributes)
    assert attrs.get("pinecone.rows_failed") == 1

    event_names = [e.name for e in sync_span.events]
    assert "row_upsert_failed" in event_names
    failed_event = next(e for e in sync_span.events if e.name == "row_upsert_failed")
    assert failed_event.attributes.get("job_id") == str(entry.job_id)


@pytest.mark.asyncio
async def test_span_emitted_when_message_missing(span_exporter):
    """Span still emitted when message row not found."""
    from src.temporal.activities import process_message_activity

    inp = ProcessMessageInput(
        message_sid="SMnotfound",
        from_number="+15551234567",
        body="test",
    )

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_row = MagicMock()
    mock_row.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_row)

    mock_sessionmaker = MagicMock(return_value=mock_session)

    from temporalio.exceptions import ApplicationError

    with (
        patch(
            "src.temporal.activities.get_sessionmaker",
            return_value=mock_sessionmaker,
        ),
        patch("src.temporal.activities.hash_phone", return_value="hashed"),
        pytest.raises(ApplicationError),
    ):
        await process_message_activity(inp)

    spans = span_exporter.get_finished_spans()
    span_names = [s.name for s in spans]
    assert "temporal.process_message" in span_names
