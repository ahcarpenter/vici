from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

import src.temporal.activities as acts
from src.extraction.constants import SyncStatus
from src.extraction.models import PineconeSyncQueue
from src.temporal.activities import (
    ProcessMessageInput,
    handle_process_message_failure_activity,
    process_message_activity,
    purge_rate_limit_activity,
    sync_pinecone_queue_activity,
)


def _make_input(
    message_sid="SMtest",
    from_number="+13125551234",
    body="hello",
):
    return ProcessMessageInput(
        message_sid=message_sid,
        from_number=from_number,
        body=body,
    )


def _make_message_row(message_id=1, user_id=42):
    row = MagicMock()
    row.id = message_id
    row.user_id = user_id
    return row


def _setup_session_mock():
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    mock_sessionmaker = MagicMock(
        return_value=MagicMock(
            __aenter__=AsyncMock(return_value=mock_session),
            __aexit__=AsyncMock(return_value=None),
        )
    )
    return mock_session, mock_sessionmaker


@pytest.mark.asyncio
async def test_process_message_job():
    """Job classification: orchestrator.run called, returns ok."""
    inp = _make_input(body="Need a mover Saturday downtown Chicago $25/hr")
    mock_message = _make_message_row()

    mock_session, mock_sessionmaker = _setup_session_mock()
    mock_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_message))
    )

    mock_orchestrator = AsyncMock()
    mock_orchestrator.run = AsyncMock(return_value=None)

    original = acts._orchestrator
    acts._orchestrator = mock_orchestrator
    try:
        with patch(
            "src.temporal.activities.get_sessionmaker",
            return_value=mock_sessionmaker,
        ):
            result = await process_message_activity(inp)
    finally:
        acts._orchestrator = original

    assert result == "ok"
    mock_orchestrator.run.assert_awaited_once()
    kw = mock_orchestrator.run.call_args.kwargs
    assert kw["message_sid"] == "SMtest"
    assert kw["message_id"] == 1
    assert kw["user_id"] == 42


@pytest.mark.asyncio
async def test_process_message_worker():
    """Worker classification: orchestrator.run called, returns ok."""
    inp = _make_input(body="I need $200 today")
    mock_message = _make_message_row()

    mock_session, mock_sessionmaker = _setup_session_mock()
    mock_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_message))
    )

    mock_orchestrator = AsyncMock()
    mock_orchestrator.run = AsyncMock(return_value=None)

    original = acts._orchestrator
    acts._orchestrator = mock_orchestrator
    try:
        with patch(
            "src.temporal.activities.get_sessionmaker",
            return_value=mock_sessionmaker,
        ):
            result = await process_message_activity(inp)
    finally:
        acts._orchestrator = original

    assert result == "ok"
    mock_orchestrator.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_message_unknown():
    """Unknown classification: orchestrator.run called."""
    inp = _make_input(body="Hello", from_number="+13125551234")
    mock_message = _make_message_row()

    mock_session, mock_sessionmaker = _setup_session_mock()
    mock_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_message))
    )

    mock_orchestrator = AsyncMock()
    mock_orchestrator.run = AsyncMock(return_value=None)

    original = acts._orchestrator
    acts._orchestrator = mock_orchestrator
    try:
        with patch(
            "src.temporal.activities.get_sessionmaker",
            return_value=mock_sessionmaker,
        ):
            result = await process_message_activity(inp)
    finally:
        acts._orchestrator = original

    assert result == "ok"
    mock_orchestrator.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_message_not_found():
    """Message row missing: raises ApplicationError(non_retryable=True)."""
    from temporalio.exceptions import ApplicationError

    inp = _make_input(message_sid="SM_missing")

    mock_session, mock_sessionmaker = _setup_session_mock()

    mock_orchestrator = AsyncMock()
    mock_orchestrator.run = AsyncMock()

    original = acts._orchestrator
    acts._orchestrator = mock_orchestrator
    try:
        with (
            patch(
                "src.temporal.activities.get_sessionmaker",
                return_value=mock_sessionmaker,
            ),
            pytest.raises(ApplicationError) as exc_info,
        ):
            await process_message_activity(inp)
        assert exc_info.value.non_retryable is True
    finally:
        acts._orchestrator = original

    mock_orchestrator.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_failure_increments_counter():
    """Failure activity increments pipeline_failures_total counter."""
    from src.metrics import pipeline_failures_total

    inp = _make_input(message_sid="SM123")

    before = pipeline_failures_total.labels(function="process-message")._value.get()
    await handle_process_message_failure_activity(inp)
    after = pipeline_failures_total.labels(function="process-message")._value.get()
    assert after == before + 1


# --- sync_pinecone_queue tests (real DB via async_session fixture) ---


def _sessionmaker_over(session):
    """Factory whose sessions are non-closing wrappers around *session*, so the
    activity's `async with get_sessionmaker()() as s:` uses the test session."""

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
async def test_sync_pinecone_queue_success_path(async_session, make_pending_entry):
    """Pending entry processed and marked synced."""
    entry = await make_pending_entry(description="Mover needed")
    mock_write = AsyncMock(return_value=None)

    original = acts._openai_client
    acts._openai_client = MagicMock()
    try:
        with (
            patch(
                "src.temporal.activities.get_sessionmaker",
                return_value=_sessionmaker_over(async_session),
            ),
            patch("src.temporal.activities.write_job_embedding", mock_write),
            patch("src.temporal.activities.get_settings", return_value=MagicMock()),
        ):
            result = await sync_pinecone_queue_activity()
    finally:
        acts._openai_client = original

    assert result == "ok"
    assert mock_write.await_count == 1
    kw = mock_write.call_args.kwargs
    assert kw["job_id"] == entry.job_id
    assert kw["description"] == "Mover needed"

    assert entry.status == SyncStatus.SYNCED


@pytest.mark.asyncio
async def test_sync_pinecone_queue_failure_path(async_session, make_pending_entry):
    """write_job_embedding raises: entry marked failed with attempts + error."""
    entry = await make_pending_entry()
    mock_write = AsyncMock(side_effect=Exception("Pinecone timeout"))

    original = acts._openai_client
    acts._openai_client = MagicMock()
    try:
        with (
            patch(
                "src.temporal.activities.get_sessionmaker",
                return_value=_sessionmaker_over(async_session),
            ),
            patch("src.temporal.activities.write_job_embedding", mock_write),
            patch("src.temporal.activities.get_settings", return_value=MagicMock()),
        ):
            result = await sync_pinecone_queue_activity()
    finally:
        acts._openai_client = original

    assert result == "ok"
    assert entry.status == SyncStatus.FAILED
    assert entry.attempts == 1
    assert "Pinecone timeout" in entry.last_error


@pytest.mark.asyncio
async def test_sync_pinecone_queue_empty_queue(async_session):
    """No pending rows: returns ok, no writes."""
    mock_write = AsyncMock(return_value=None)

    original = acts._openai_client
    acts._openai_client = MagicMock()
    try:
        with (
            patch(
                "src.temporal.activities.get_sessionmaker",
                return_value=_sessionmaker_over(async_session),
            ),
            patch("src.temporal.activities.write_job_embedding", mock_write),
        ):
            result = await sync_pinecone_queue_activity()
    finally:
        acts._openai_client = original

    assert result == "ok"
    mock_write.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_pinecone_queue_mixed_rows(async_session, make_pending_entry):
    """Multiple rows: success and failure paths coexist."""
    entry_ok = await make_pending_entry()
    entry_bad = await make_pending_entry()

    mock_write = AsyncMock(side_effect=[None, Exception("Pinecone error")])

    original = acts._openai_client
    acts._openai_client = MagicMock()
    try:
        with (
            patch(
                "src.temporal.activities.get_sessionmaker",
                return_value=_sessionmaker_over(async_session),
            ),
            patch("src.temporal.activities.write_job_embedding", mock_write),
            patch("src.temporal.activities.get_settings", return_value=MagicMock()),
        ):
            result = await sync_pinecone_queue_activity()
    finally:
        acts._openai_client = original

    assert result == "ok"
    assert mock_write.await_count == 2
    assert entry_ok.status == SyncStatus.SYNCED
    assert entry_bad.status == SyncStatus.FAILED


@pytest.mark.asyncio
async def test_purge_rate_limit_deletes_expired_rows(async_session, make_user):
    """Rows older than the retention window are deleted; fresh rows survive."""
    from datetime import UTC, datetime, timedelta

    from sqlmodel import select

    from src.sms.constants import RATE_LIMIT_PURGE_RETENTION
    from src.sms.models import RateLimit

    user = await make_user()
    now = datetime.now(UTC)
    stale = RateLimit(
        user_id=user.id,
        created_at=now - RATE_LIMIT_PURGE_RETENTION - timedelta(minutes=1),
    )
    fresh = RateLimit(user_id=user.id, created_at=now)
    async_session.add(stale)
    async_session.add(fresh)
    await async_session.flush()

    with patch(
        "src.temporal.activities.get_sessionmaker",
        return_value=_sessionmaker_over(async_session),
    ):
        result = await purge_rate_limit_activity()

    assert result == "ok"
    remaining = (
        (
            await async_session.execute(
                select(RateLimit).where(RateLimit.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert [r.id for r in remaining] == [fresh.id]


@pytest.mark.asyncio
async def test_sync_pinecone_queue_skips_non_pending(async_session, make_pending_entry):
    """Synced/failed entries are not re-processed."""
    entry = await make_pending_entry()
    entry.status = SyncStatus.SYNCED
    await async_session.flush()

    mock_write = AsyncMock(return_value=None)

    original = acts._openai_client
    acts._openai_client = MagicMock()
    try:
        with (
            patch(
                "src.temporal.activities.get_sessionmaker",
                return_value=_sessionmaker_over(async_session),
            ),
            patch("src.temporal.activities.write_job_embedding", mock_write),
        ):
            result = await sync_pinecone_queue_activity()
    finally:
        acts._openai_client = original

    assert result == "ok"
    mock_write.assert_not_awaited()
