from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.temporal.activities as acts
from src.temporal.activities import (
    ProcessMessageInput,
    handle_process_message_failure_activity,
    process_message_activity,
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
        return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None)
        )
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
        return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=mock_message)
        )
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
        return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=mock_message)
        )
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
        return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=mock_message)
        )
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
        with patch(
            "src.temporal.activities.get_sessionmaker",
            return_value=mock_sessionmaker,
        ):
            with pytest.raises(ApplicationError) as exc_info:
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

    before = pipeline_failures_total.labels(
        function="process-message"
    )._value.get()
    await handle_process_message_failure_activity(inp)
    after = pipeline_failures_total.labels(
        function="process-message"
    )._value.get()
    assert after == before + 1


# --- sync_pinecone_queue tests ---


def _make_pending_row(
    row_id=1, job_id=10, description="Mover needed", phone_hash="abc123"
):
    return {
        "id": row_id,
        "job_id": job_id,
        "description": description,
        "phone_hash": phone_hash,
    }


@pytest.mark.asyncio
async def test_sync_pinecone_queue_success_path():
    """Pending row processed, status updated to success."""
    row = _make_pending_row()
    mock_write = AsyncMock(return_value=None)
    mock_openai = MagicMock()

    select_session = AsyncMock()
    update_session = AsyncMock()

    select_result = MagicMock()
    select_result.mappings.return_value.all.return_value = [row]
    select_session.execute = AsyncMock(return_value=select_result)

    update_session.execute = AsyncMock(return_value=MagicMock())
    update_session.commit = AsyncMock()

    call_count = {"n": 0}

    def make_session():
        call_count["n"] += 1
        if call_count["n"] == 1:
            cm = MagicMock()
            cm.__aenter__ = AsyncMock(return_value=select_session)
            cm.__aexit__ = AsyncMock(return_value=None)
        else:
            cm = MagicMock()
            cm.__aenter__ = AsyncMock(return_value=update_session)
            cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    mock_sessionmaker = MagicMock(side_effect=make_session)

    mock_settings = MagicMock()
    original = acts._openai_client
    acts._openai_client = mock_openai
    try:
        with (
            patch(
                "src.temporal.activities.get_sessionmaker",
                return_value=mock_sessionmaker,
            ),
            patch(
                "src.temporal.activities.write_job_embedding",
                mock_write,
            ),
            patch(
                "src.temporal.activities.get_settings",
                return_value=mock_settings,
            ),
        ):
            result = await sync_pinecone_queue_activity()
    finally:
        acts._openai_client = original

    assert result == "ok"
    assert mock_write.await_count == 1
    kw = mock_write.call_args.kwargs
    assert kw["job_id"] == 10
    assert kw["description"] == "Mover needed"

    query_str = str(update_session.execute.call_args.args[0])
    assert "success" in query_str


@pytest.mark.asyncio
async def test_sync_pinecone_queue_failure_path():
    """write_job_embedding raises: status updated to failed."""
    row = _make_pending_row(row_id=2, job_id=20)
    mock_write = AsyncMock(side_effect=Exception("Pinecone timeout"))
    mock_openai = MagicMock()

    select_session = AsyncMock()
    update_session = AsyncMock()

    select_result = MagicMock()
    select_result.mappings.return_value.all.return_value = [row]
    select_session.execute = AsyncMock(return_value=select_result)

    update_session.execute = AsyncMock(return_value=MagicMock())
    update_session.commit = AsyncMock()

    call_count = {"n": 0}

    def make_session():
        call_count["n"] += 1
        if call_count["n"] == 1:
            cm = MagicMock()
            cm.__aenter__ = AsyncMock(return_value=select_session)
            cm.__aexit__ = AsyncMock(return_value=None)
        else:
            cm = MagicMock()
            cm.__aenter__ = AsyncMock(return_value=update_session)
            cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    mock_sessionmaker = MagicMock(side_effect=make_session)

    mock_settings = MagicMock()
    original = acts._openai_client
    acts._openai_client = mock_openai
    try:
        with (
            patch(
                "src.temporal.activities.get_sessionmaker",
                return_value=mock_sessionmaker,
            ),
            patch(
                "src.temporal.activities.write_job_embedding",
                mock_write,
            ),
            patch(
                "src.temporal.activities.get_settings",
                return_value=mock_settings,
            ),
        ):
            result = await sync_pinecone_queue_activity()
    finally:
        acts._openai_client = original

    assert result == "ok"
    query_str = str(update_session.execute.call_args.args[0])
    assert "failed" in query_str
    assert "retry_count" in query_str


@pytest.mark.asyncio
async def test_sync_pinecone_queue_empty_queue():
    """No pending rows: returns ok, no writes."""
    mock_write = AsyncMock(return_value=None)
    mock_openai = MagicMock()

    select_session = AsyncMock()
    select_result = MagicMock()
    select_result.mappings.return_value.all.return_value = []
    select_session.execute = AsyncMock(return_value=select_result)

    def make_session():
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=select_session)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    mock_sessionmaker = MagicMock(side_effect=make_session)

    original = acts._openai_client
    acts._openai_client = mock_openai
    try:
        with (
            patch(
                "src.temporal.activities.get_sessionmaker",
                return_value=mock_sessionmaker,
            ),
            patch(
                "src.temporal.activities.write_job_embedding",
                mock_write,
            ),
        ):
            result = await sync_pinecone_queue_activity()
    finally:
        acts._openai_client = original

    assert result == "ok"
    mock_write.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_pinecone_queue_mixed_rows():
    """Multiple rows: success and failure paths coexist."""
    row1 = _make_pending_row(row_id=1, job_id=10)
    row2 = _make_pending_row(row_id=2, job_id=20)

    mock_write = AsyncMock(
        side_effect=[None, Exception("Pinecone error")]
    )
    mock_openai = MagicMock()

    select_session = AsyncMock()
    select_result = MagicMock()
    select_result.mappings.return_value.all.return_value = [row1, row2]
    select_session.execute = AsyncMock(return_value=select_result)

    update_sessions = []

    def make_update_session():
        s = AsyncMock()
        s.execute = AsyncMock(return_value=MagicMock())
        s.commit = AsyncMock()
        update_sessions.append(s)
        return s

    call_count = {"n": 0}

    def make_session():
        call_count["n"] += 1
        if call_count["n"] == 1:
            cm = MagicMock()
            cm.__aenter__ = AsyncMock(return_value=select_session)
            cm.__aexit__ = AsyncMock(return_value=None)
        else:
            s = make_update_session()
            cm = MagicMock()
            cm.__aenter__ = AsyncMock(return_value=s)
            cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    mock_sessionmaker = MagicMock(side_effect=make_session)

    mock_settings = MagicMock()
    original = acts._openai_client
    acts._openai_client = mock_openai
    try:
        with (
            patch(
                "src.temporal.activities.get_sessionmaker",
                return_value=mock_sessionmaker,
            ),
            patch(
                "src.temporal.activities.write_job_embedding",
                mock_write,
            ),
            patch(
                "src.temporal.activities.get_settings",
                return_value=mock_settings,
            ),
        ):
            result = await sync_pinecone_queue_activity()
    finally:
        acts._openai_client = original

    assert result == "ok"
    assert mock_write.await_count == 2

    q1 = str(update_sessions[0].execute.call_args.args[0])
    assert "success" in q1

    q2 = str(update_sessions[1].execute.call_args.args[0])
    assert "failed" in q2
