from unittest.mock import AsyncMock, MagicMock, patch

import inngest
import pytest

import src.inngest_client as ic
from src.extraction.schemas import (
    ExtractionResult,
    JobExtraction,
    UnknownMessage,
    WorkerExtraction,
)


def _make_ctx(message_sid="SMtest", from_number="+13125551234", body="hello"):
    """Build a minimal Inngest Context object for process_message tests."""
    event = MagicMock(spec=inngest.Event)
    event.data = {
        "message_sid": message_sid,
        "from_number": from_number,
        "body": body,
    }
    ctx = MagicMock(spec=inngest.Context)
    ctx.event = event
    return ctx


def _make_message_row(message_id=1, user_id=42):
    """Minimal Message ORM stub."""
    row = MagicMock()
    row.id = message_id
    row.user_id = user_id
    return row


def _make_extraction_result(message_type: str) -> ExtractionResult:
    if message_type == "job_posting":
        job = JobExtraction(
            description="Mover needed",
            datetime_flexible=False,
            location="Chicago",
            pay_type="hourly",
        )
        return ExtractionResult(message_type="job_posting", job=job)
    elif message_type == "worker_goal":
        worker = WorkerExtraction(target_earnings=200.0, target_timeframe="today")
        return ExtractionResult(message_type="worker_goal", worker=worker)
    else:
        unknown = UnknownMessage(reason="Greeting only")
        return ExtractionResult(message_type="unknown", unknown=unknown)


def _setup_session_mock():
    """Build a mock sessionmaker that returns a usable async context manager session."""
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    mock_sessionmaker = MagicMock(return_value=MagicMock(
        __aenter__=AsyncMock(return_value=mock_session),
        __aexit__=AsyncMock(return_value=None),
    ))
    return mock_session, mock_sessionmaker


@pytest.mark.asyncio
async def test_process_message_job():
    """Job classification: orchestrator.run called, returns ok."""
    ctx = _make_ctx(body="Need a mover Saturday downtown Chicago $25/hr")
    mock_message = _make_message_row()
    extraction_result = _make_extraction_result("job_posting")

    mock_session, mock_sessionmaker = _setup_session_mock()
    mock_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_message))
    )

    mock_orchestrator = AsyncMock()
    mock_orchestrator.run = AsyncMock(return_value=extraction_result)

    original_orchestrator = ic._orchestrator
    ic._orchestrator = mock_orchestrator
    try:
        with patch("src.inngest_client.get_sessionmaker", return_value=mock_sessionmaker):
            from src.inngest_client import process_message
            result = await process_message._handler(ctx)
    finally:
        ic._orchestrator = original_orchestrator

    assert result == "ok"
    mock_orchestrator.run.assert_awaited_once()
    call_kwargs = mock_orchestrator.run.call_args.kwargs
    assert call_kwargs["message_sid"] == "SMtest"
    assert call_kwargs["message_id"] == 1
    assert call_kwargs["user_id"] == 42


@pytest.mark.asyncio
async def test_process_message_worker():
    """Worker classification: orchestrator.run called, returns ok."""
    ctx = _make_ctx(body="I need $200 today")
    mock_message = _make_message_row()
    extraction_result = _make_extraction_result("worker_goal")

    mock_session, mock_sessionmaker = _setup_session_mock()
    mock_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_message))
    )

    mock_orchestrator = AsyncMock()
    mock_orchestrator.run = AsyncMock(return_value=extraction_result)

    original_orchestrator = ic._orchestrator
    ic._orchestrator = mock_orchestrator
    try:
        with patch("src.inngest_client.get_sessionmaker", return_value=mock_sessionmaker):
            from src.inngest_client import process_message
            result = await process_message._handler(ctx)
    finally:
        ic._orchestrator = original_orchestrator

    assert result == "ok"
    mock_orchestrator.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_message_unknown():
    """Unknown classification: orchestrator.run called (orchestrator handles Twilio reply)."""
    ctx = _make_ctx(body="Hello", from_number="+13125551234")
    mock_message = _make_message_row()
    extraction_result = _make_extraction_result("unknown")

    mock_session, mock_sessionmaker = _setup_session_mock()
    mock_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_message))
    )

    mock_orchestrator = AsyncMock()
    mock_orchestrator.run = AsyncMock(return_value=extraction_result)

    original_orchestrator = ic._orchestrator
    ic._orchestrator = mock_orchestrator
    try:
        with patch("src.inngest_client.get_sessionmaker", return_value=mock_sessionmaker):
            from src.inngest_client import process_message
            result = await process_message._handler(ctx)
    finally:
        ic._orchestrator = original_orchestrator

    assert result == "ok"
    mock_orchestrator.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_message_not_found():
    """Message row missing from DB: returns ok without calling orchestrator."""
    ctx = _make_ctx(message_sid="SM_missing")

    mock_session, mock_sessionmaker = _setup_session_mock()
    # scalar_one_or_none returns None (default in _setup_session_mock)

    mock_orchestrator = AsyncMock()
    mock_orchestrator.run = AsyncMock()

    original_orchestrator = ic._orchestrator
    ic._orchestrator = mock_orchestrator
    try:
        with patch("src.inngest_client.get_sessionmaker", return_value=mock_sessionmaker):
            from src.inngest_client import process_message
            result = await process_message._handler(ctx)
    finally:
        ic._orchestrator = original_orchestrator

    assert result == "ok"
    mock_orchestrator.run.assert_not_awaited()


# ---------------------------------------------------------------------------
# on_failure handler tests (plan 02.5-04)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_failure_increments_counter():
    """_handle_process_message_failure increments pipeline_failures_total counter."""
    from src.inngest_client import _handle_process_message_failure
    from src.metrics import pipeline_failures_total

    ctx = MagicMock()
    ctx.event.data = {"message_sid": "SM123"}
    ctx.attempt = 3

    before = pipeline_failures_total.labels(function="process-message")._value.get()
    await _handle_process_message_failure(ctx)
    after = pipeline_failures_total.labels(function="process-message")._value.get()
    assert after == before + 1
