"""
Integration / handler tests: job posting flow.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_job_posting_queue_insert_failure_is_caught():
    """Pinecone upsert AND queue INSERT both fail:
    no exception propagated, error logged."""
    from src.extraction.schemas import ExtractionResult, JobExtraction
    from src.pipeline.context import PipelineContext
    from src.pipeline.handlers.job_posting import JobPostingHandler

    mock_extraction_service = MagicMock()
    mock_extraction_service.settings.sms.from_number = "+10000000000"
    mock_extraction_service.openai_client = MagicMock()

    mock_job_repo = MagicMock()
    mock_job = MagicMock()
    mock_job.id = 99
    mock_job_repo.create = AsyncMock(return_value=mock_job)

    mock_audit_repo = MagicMock()
    mock_audit_repo.write = AsyncMock()

    async def pinecone_that_raises(**kwargs):
        raise Exception("Pinecone down")

    handler = JobPostingHandler(
        job_repo=mock_job_repo,
        audit_repo=mock_audit_repo,
        pinecone_client=pinecone_that_raises,
        extraction_service=mock_extraction_service,
    )

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    ctx = MagicMock(spec=PipelineContext)
    ctx.message_id = 1
    ctx.message_sid = "SMtest"
    ctx.from_number = "+13125551234"
    ctx.phone_hash = "abc123"
    ctx.user_id = 1
    ctx.sms_text = "Need a mover"
    ctx.session = mock_session
    ctx.result = ExtractionResult(
        message_type="job_posting",
        job=JobExtraction(
            description="Need a mover",
            datetime_flexible=True,
            location="Chicago",
            pay_type="hourly",
        ),
    )

    logged_errors = []

    class CapturingLogger:
        def error(self, event, **kw):
            logged_errors.append(event)

        def info(self, *a, **kw):
            pass

        def warning(self, *a, **kw):
            pass

    failing_session = AsyncMock()
    failing_session.execute = AsyncMock(side_effect=Exception("DB down"))
    failing_session.commit = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=failing_session)
    cm.__aexit__ = AsyncMock(return_value=None)
    mock_sessionmaker_fn = MagicMock(return_value=cm)

    with (
        patch("src.pipeline.handlers.job_posting.log", CapturingLogger()),
        patch(
            "src.pipeline.handlers.job_posting.get_sessionmaker",
            return_value=mock_sessionmaker_fn,
        ),
    ):
        # Should not raise
        await handler.handle(ctx)

    assert any("pinecone_write_failed" in e for e in logged_errors)
    assert any("pinecone_queue_insert_failed" in e for e in logged_errors)


@pytest.mark.asyncio
async def test_rate_limit_rolling_window():
    """enforce_rate_limit uses rolling 60-second window (interval arithmetic)."""
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
