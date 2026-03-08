"""Tests for sync_pinecone_queue sweep logic."""
from unittest.mock import AsyncMock, MagicMock, patch

import inngest
import pytest

import src.inngest_client as ic


def _make_ctx():
    """Build a minimal Inngest Context object for sync_pinecone_queue tests."""
    event = MagicMock(spec=inngest.Event)
    event.data = {}
    ctx = MagicMock(spec=inngest.Context)
    ctx.event = event
    return ctx


def _make_pending_row(row_id=1, job_id=10, description="Mover needed", phone_hash="abc123"):
    """Build a mapping-like row from the DB result."""
    row = {
        "id": row_id,
        "job_id": job_id,
        "description": description,
        "phone_hash": phone_hash,
    }
    return row


def _setup_session_mock(rows: list):
    """
    Build a mock sessionmaker that returns a DB session whose execute() returns
    rows as mappings for the SELECT query, and a no-op for UPDATE queries.
    """
    # The sessionmaker is called multiple times (once per session context).
    # We need each call to __call__ to return a fresh async context manager.
    def make_session_ctx():
        mock_session = AsyncMock()

        # First call to execute returns the rows (SELECT); subsequent calls are UPDATEs
        select_result = MagicMock()
        select_result.mappings.return_value.all.return_value = rows

        update_result = MagicMock()

        call_count = {"n": 0}

        async def execute_side_effect(query, *args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return select_result
            return update_result

        mock_session.execute = AsyncMock(side_effect=execute_side_effect)
        mock_session.commit = AsyncMock()
        ctx_mgr = MagicMock()
        ctx_mgr.__aenter__ = AsyncMock(return_value=mock_session)
        ctx_mgr.__aexit__ = AsyncMock(return_value=None)
        return ctx_mgr

    # The SELECT session is one call; each row UPDATE is a separate session call.
    # We model this as: each call to mock_sessionmaker() returns a new session ctx.
    sessions = []

    def sessionmaker_factory():
        ctx = make_session_ctx()
        sessions.append(ctx)
        return ctx

    mock_sessionmaker = MagicMock(side_effect=sessionmaker_factory)
    return mock_sessionmaker, sessions


@pytest.mark.asyncio
async def test_sync_pinecone_queue_success_path():
    """
    Given one pending row, write_job_embedding is called with correct args
    and status is updated to 'success'.
    """
    ctx = _make_ctx()
    row = _make_pending_row(row_id=1, job_id=10, description="Mover needed", phone_hash="abc123")

    mock_write = AsyncMock(return_value=None)
    mock_openai = MagicMock()

    # Each session is independent: SELECT session, then UPDATE session
    select_session = AsyncMock()
    update_session = AsyncMock()

    select_result = MagicMock()
    select_result.mappings.return_value.all.return_value = [row]
    select_session.execute = AsyncMock(return_value=select_result)
    select_session.commit = AsyncMock()

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

    original_openai = ic._openai_client
    ic._openai_client = mock_openai
    try:
        with patch("src.inngest_client.get_sessionmaker", return_value=mock_sessionmaker), \
             patch("src.inngest_client.write_job_embedding", mock_write):
            from src.inngest_client import sync_pinecone_queue
            result = await sync_pinecone_queue._handler(ctx)
    finally:
        ic._openai_client = original_openai

    assert result == "ok"
    assert mock_write.await_count == 1
    # Check actual call args
    call_kwargs = mock_write.call_args.kwargs
    assert call_kwargs["job_id"] == 10
    assert call_kwargs["description"] == "Mover needed"
    assert call_kwargs["phone_hash"] == "abc123"
    assert call_kwargs["openai_client"] is mock_openai

    # UPDATE was called with status='success'
    update_call_args = update_session.execute.call_args
    query_str = str(update_call_args.args[0])
    assert "success" in query_str
    assert update_session.commit.await_count == 1


@pytest.mark.asyncio
async def test_sync_pinecone_queue_failure_path():
    """
    Given write_job_embedding raises, status is updated to 'failed',
    retry_count incremented, a warning is logged, and function returns 'ok'.
    """
    ctx = _make_ctx()
    row = _make_pending_row(row_id=2, job_id=20, description="Driver needed", phone_hash="def456")

    mock_write = AsyncMock(side_effect=Exception("Pinecone timeout"))
    mock_openai = MagicMock()

    select_session = AsyncMock()
    update_session = AsyncMock()

    select_result = MagicMock()
    select_result.mappings.return_value.all.return_value = [row]
    select_session.execute = AsyncMock(return_value=select_result)
    select_session.commit = AsyncMock()

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

    original_openai = ic._openai_client
    ic._openai_client = mock_openai
    try:
        with patch("src.inngest_client.get_sessionmaker", return_value=mock_sessionmaker), \
             patch("src.inngest_client.write_job_embedding", mock_write):
            from src.inngest_client import sync_pinecone_queue
            result = await sync_pinecone_queue._handler(ctx)
    finally:
        ic._openai_client = original_openai

    assert result == "ok"

    # UPDATE was called with status='failed' and retry_count increment
    update_call_args = update_session.execute.call_args
    query_str = str(update_call_args.args[0])
    assert "failed" in query_str
    assert "retry_count" in query_str
    assert update_session.commit.await_count == 1


@pytest.mark.asyncio
async def test_sync_pinecone_queue_empty_queue():
    """
    Given no pending rows, function returns 'ok' with no write_job_embedding calls.
    """
    ctx = _make_ctx()

    mock_write = AsyncMock(return_value=None)
    mock_openai = MagicMock()

    select_session = AsyncMock()

    select_result = MagicMock()
    select_result.mappings.return_value.all.return_value = []
    select_session.execute = AsyncMock(return_value=select_result)
    select_session.commit = AsyncMock()

    def make_session():
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=select_session)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    mock_sessionmaker = MagicMock(side_effect=make_session)

    original_openai = ic._openai_client
    ic._openai_client = mock_openai
    try:
        with patch("src.inngest_client.get_sessionmaker", return_value=mock_sessionmaker), \
             patch("src.inngest_client.write_job_embedding", mock_write):
            from src.inngest_client import sync_pinecone_queue
            result = await sync_pinecone_queue._handler(ctx)
    finally:
        ic._openai_client = original_openai

    assert result == "ok"
    mock_write.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_pinecone_queue_mixed_rows():
    """
    Given multiple pending rows, all are processed — success and failure paths coexist.
    """
    ctx = _make_ctx()
    row1 = _make_pending_row(row_id=1, job_id=10, description="Mover needed", phone_hash="abc123")
    row2 = _make_pending_row(row_id=2, job_id=20, description="Driver needed", phone_hash="def456")

    # write_job_embedding: first call succeeds, second raises
    mock_write = AsyncMock(side_effect=[None, Exception("Pinecone error")])
    mock_openai = MagicMock()

    select_session = AsyncMock()
    select_result = MagicMock()
    select_result.mappings.return_value.all.return_value = [row1, row2]
    select_session.execute = AsyncMock(return_value=select_result)
    select_session.commit = AsyncMock()

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

    original_openai = ic._openai_client
    ic._openai_client = mock_openai
    try:
        with patch("src.inngest_client.get_sessionmaker", return_value=mock_sessionmaker), \
             patch("src.inngest_client.write_job_embedding", mock_write):
            from src.inngest_client import sync_pinecone_queue
            result = await sync_pinecone_queue._handler(ctx)
    finally:
        ic._openai_client = original_openai

    assert result == "ok"
    assert mock_write.await_count == 2

    # First update: success
    query_str_1 = str(update_sessions[0].execute.call_args.args[0])
    assert "success" in query_str_1

    # Second update: failed
    query_str_2 = str(update_sessions[1].execute.call_args.args[0])
    assert "failed" in query_str_2
