"""Tests for OTel span emission in temporal activities."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

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
        patch(
            "src.temporal.activities.hash_phone", return_value="hashed"
        ),
    ):
        await process_message_activity(inp)

    spans = span_exporter.get_finished_spans()
    span_names = [s.name for s in spans]
    assert "temporal.process_message" in span_names

    temporal_span = next(
        s for s in spans if s.name == "temporal.process_message"
    )
    attrs = dict(temporal_span.attributes)
    assert attrs.get("temporal.event") == "message.received"
    assert attrs.get("temporal.function") == "process-message"


@pytest.mark.asyncio
async def test_sync_pinecone_queue_emits_span(span_exporter):
    """Activity emits span named temporal.sync_pinecone_queue with row attributes."""
    from src.temporal.activities import sync_pinecone_queue_activity
    import src.temporal.activities as acts

    row = {"id": 1, "job_id": 10, "description": "Mover needed", "phone_hash": "abc"}

    select_session = AsyncMock()
    select_result = MagicMock()
    select_result.mappings.return_value.all.return_value = [row]
    select_session.execute = AsyncMock(return_value=select_result)

    update_session = AsyncMock()
    update_session.execute = AsyncMock(return_value=MagicMock())
    update_session.commit = AsyncMock()

    call_count = {"n": 0}

    def make_session():
        call_count["n"] += 1
        cm = MagicMock()
        if call_count["n"] == 1:
            cm.__aenter__ = AsyncMock(return_value=select_session)
        else:
            cm.__aenter__ = AsyncMock(return_value=update_session)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    original_openai = acts._openai_client
    acts._openai_client = MagicMock()
    try:
        with (
            patch(
                "src.temporal.activities.get_sessionmaker",
                return_value=MagicMock(side_effect=make_session),
            ),
            patch(
                "src.temporal.activities.write_job_embedding",
                AsyncMock(return_value=None),
            ),
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
async def test_sync_pinecone_queue_span_records_failure_event(span_exporter):
    """Failed row adds row_upsert_failed event to span."""
    from src.temporal.activities import sync_pinecone_queue_activity
    import src.temporal.activities as acts

    row = {"id": 2, "job_id": 20, "description": "Test", "phone_hash": "xyz"}

    select_session = AsyncMock()
    select_result = MagicMock()
    select_result.mappings.return_value.all.return_value = [row]
    select_session.execute = AsyncMock(return_value=select_result)

    update_session = AsyncMock()
    update_session.execute = AsyncMock(return_value=MagicMock())
    update_session.commit = AsyncMock()

    call_count = {"n": 0}

    def make_session():
        call_count["n"] += 1
        cm = MagicMock()
        if call_count["n"] == 1:
            cm.__aenter__ = AsyncMock(return_value=select_session)
        else:
            cm.__aenter__ = AsyncMock(return_value=update_session)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    original_openai = acts._openai_client
    acts._openai_client = MagicMock()
    try:
        with (
            patch(
                "src.temporal.activities.get_sessionmaker",
                return_value=MagicMock(side_effect=make_session),
            ),
            patch(
                "src.temporal.activities.write_job_embedding",
                AsyncMock(side_effect=Exception("timeout")),
            ),
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
    assert failed_event.attributes.get("job_id") == "20"


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

    with (
        patch(
            "src.temporal.activities.get_sessionmaker",
            return_value=mock_sessionmaker,
        ),
        patch(
            "src.temporal.activities.hash_phone", return_value="hashed"
        ),
    ):
        await process_message_activity(inp)

    spans = span_exporter.get_finished_spans()
    span_names = [s.name for s in spans]
    assert "temporal.process_message" in span_names
