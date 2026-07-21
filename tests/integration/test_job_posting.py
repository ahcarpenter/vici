"""
Integration / handler tests: job posting flow.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_job_posting_queue_insert_failure_is_caught():
    """Pinecone upsert AND queue INSERT both fail: no exception."""
    from src.extraction.schemas import ExtractionResult, JobExtraction
    from src.pipeline.context import PipelineContext
    from src.pipeline.handlers.job_posting import JobPostingHandler

    mock_job_repo = MagicMock()
    mock_job = MagicMock()
    mock_job.id = 99
    mock_job_repo.create = AsyncMock(return_value=mock_job)

    mock_audit_repo = MagicMock()
    mock_audit_repo.write = AsyncMock()

    async def embedding_writer_that_raises(**kwargs):
        raise Exception("Pinecone down")

    mock_sync_queue_repo = MagicMock()
    mock_sync_queue_repo.enqueue = AsyncMock(side_effect=Exception("DB down"))

    handler = JobPostingHandler(
        job_repo=mock_job_repo,
        audit_repo=mock_audit_repo,
        job_embedding_writer=embedding_writer_that_raises,
        sync_queue_repo=mock_sync_queue_repo,
    )

    mock_session = AsyncMock()

    ctx = PipelineContext(
        session=mock_session,
        result=ExtractionResult(
            message_type="job_posting",
            job=JobExtraction(
                description="Need a mover",
                datetime_flexible=True,
                location="Chicago",
                pay_type="hourly",
            ),
        ),
        sms_text="Need a mover",
        phone_hash="abc123",
        message_id=1,
        user_id=1,
        message_sid="SMtest",
        from_number="+13125551234",
    )

    logged_errors = []

    class CapturingLogger:
        def error(self, event, **kw):
            logged_errors.append(event)

        def info(self, *a, **kw):
            pass

        def warning(self, *a, **kw):
            pass

    with patch("src.pipeline.handlers.job_posting.log", CapturingLogger()):
        # Should not raise: handler stages the write, deferred action degrades
        await handler.handle(ctx)
        mock_session.commit.reset_mock()  # only deferred-action commits count below
        for action in ctx.post_commit_actions:
            await action()

    assert any("pinecone_write_failed" in e for e in logged_errors)
    assert any("pinecone_queue_insert_failed" in e for e in logged_errors)
    # Failed enqueue must roll back, not commit
    mock_session.commit.assert_not_awaited()
    mock_session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_job_posting_pinecone_failure_enqueues_on_pipeline_session():
    """Pinecone failure: entry enqueued via repository on the pipeline session."""
    from src.extraction.schemas import ExtractionResult, JobExtraction
    from src.pipeline.context import PipelineContext
    from src.pipeline.handlers.job_posting import JobPostingHandler

    mock_job_repo = MagicMock()
    mock_job = MagicMock()
    mock_job.id = 7
    mock_job_repo.create = AsyncMock(return_value=mock_job)

    handler = JobPostingHandler(
        job_repo=mock_job_repo,
        audit_repo=MagicMock(write=AsyncMock()),
        job_embedding_writer=AsyncMock(side_effect=Exception("Pinecone down")),
        sync_queue_repo=MagicMock(enqueue=AsyncMock()),
    )

    mock_session = AsyncMock()
    ctx = PipelineContext(
        session=mock_session,
        result=ExtractionResult(
            message_type="job_posting",
            job=JobExtraction(
                description="Need a mover",
                datetime_flexible=True,
                location="Chicago",
                pay_type="hourly",
            ),
        ),
        sms_text="Need a mover",
        phone_hash="abc123",
        message_id=1,
        user_id=1,
        message_sid="SMtest",
        from_number="+13125551234",
    )

    await handler.handle(ctx)
    for action in ctx.post_commit_actions:
        await action()

    handler._sync_queue_repo.enqueue.assert_awaited_once_with(mock_session, 7)
    mock_session.commit.assert_awaited_once()


def test_rate_limit_rolling_window():
    """enforce_rate_limit uses rolling window (interval arithmetic)."""
    import inspect

    from src.sms.repository import MessageRepository

    src_code = inspect.getsource(MessageRepository.enforce_rate_limit)
    # Calendar-minute truncation uses replace(second=0), rolling uses timedelta
    assert "timedelta" in src_code, (
        "enforce_rate_limit should use timedelta for rolling window"
    )
    assert "replace(second=0" not in src_code, (
        "enforce_rate_limit should not use calendar-minute truncation"
    )


def test_job_create_nulls_unparseable_ideal_datetime():
    """JobCreate degrades junk LLM datetimes to None instead of raising."""
    from src.jobs.schemas import JobCreate

    job = JobCreate(
        message_id=1,
        description="Need a mover",
        location="Chicago",
        ideal_datetime="tomorrow-ish",
    )
    assert job.ideal_datetime is None
    assert job.raw_datetime_text is None  # unrelated field untouched


def test_job_create_parses_iso_and_normalizes_tz():
    """JobCreate parses ISO strings and defaults naive datetimes to UTC."""
    from datetime import UTC

    from src.jobs.schemas import JobCreate

    job = JobCreate(
        message_id=1,
        description="Need a mover",
        location="Chicago",
        ideal_datetime="2026-03-08T10:00:00",
    )
    assert job.ideal_datetime is not None
    assert job.ideal_datetime.tzinfo == UTC
