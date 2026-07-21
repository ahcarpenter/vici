"""
Integration / handler tests: work goal flow, including the match reply.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.matches.schemas import MatchResult


def _make_handler(match_result=None):
    from src.pipeline.handlers.work_goal import WorkGoalHandler

    mock_wr_repo = AsyncMock()
    mock_wr = MagicMock()
    mock_wr.id = 77
    mock_wr_repo.create = AsyncMock(return_value=mock_wr)

    mock_audit_repo = AsyncMock()
    mock_audit_repo.write = AsyncMock(return_value=None)

    if match_result is None:
        match_result = MatchResult(
            jobs=[], work_goal=mock_wr, total_earnings=0, is_partial=True
        )
    mock_match_service = AsyncMock()
    mock_match_service.match = AsyncMock(return_value=match_result)

    mock_twilio = MagicMock()

    handler = WorkGoalHandler(
        work_goal_repo=mock_wr_repo,
        audit_repo=mock_audit_repo,
        match_service=mock_match_service,
        twilio_client=mock_twilio,
        from_number="+10000000000",
    )
    return handler, mock_wr_repo, mock_match_service, mock_twilio


def _make_ctx(session, message_sid="SMwgtest", user_id=42, target_deadline=None):
    from src.extraction.schemas import ExtractionResult, WorkGoalExtraction
    from src.pipeline.context import PipelineContext

    worker = WorkGoalExtraction(
        target_earnings=150.0,
        target_timeframe="this week",
        target_deadline=target_deadline,
    )
    result = ExtractionResult(message_type="work_goal", work_goal=worker)
    return PipelineContext(
        session=session,
        result=result,
        sms_text="I want $150 this week",
        phone_hash="hashwg",
        message_id=5,
        user_id=user_id,
        message_sid=message_sid,
        from_number="+13125551234",
    )


@pytest.mark.asyncio
async def test_work_goal_handler_emits_span():
    """WorkGoalHandler emits pipeline.handle_work_goal span."""
    import src.pipeline.handlers.work_goal as wg_module
    from src.observability import OTEL_ATTR_MESSAGE_ID, OTEL_ATTR_WORK_GOAL_USER_ID

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    test_tracer = provider.get_tracer("test")
    original_tracer = wg_module.tracer
    wg_module.tracer = test_tracer

    try:
        handler, _, _, _ = _make_handler()
        mock_session = AsyncMock()
        ctx = _make_ctx(mock_session, message_sid="SMwgtest", user_id=42)

        await handler.handle(ctx)

        spans = exporter.get_finished_spans()
        span_names = [s.name for s in spans]
        assert "pipeline.handle_work_goal" in span_names, (
            f"Expected pipeline.handle_work_goal span. Got: {span_names}"
        )

        wg_span = next(s for s in spans if s.name == "pipeline.handle_work_goal")
        attrs = dict(wg_span.attributes)
        assert attrs.get(OTEL_ATTR_MESSAGE_ID) == "SMwgtest"
        assert attrs.get(OTEL_ATTR_WORK_GOAL_USER_ID) == "42"

        # Flush-only contract: the handler must not commit
        mock_session.commit.assert_not_awaited()
    finally:
        wg_module.tracer = original_tracer
        exporter.shutdown()


@pytest.mark.asyncio
async def test_work_goal_handler_matches_in_same_unit_of_work():
    """MatchService runs on the pipeline session with the created goal."""
    handler, wr_repo, match_service, _ = _make_handler()
    mock_session = AsyncMock()
    ctx = _make_ctx(mock_session)

    await handler.handle(ctx)

    match_service.match.assert_awaited_once()
    args = match_service.match.await_args.args
    assert args[0] is mock_session
    assert args[1] is wr_repo.create.return_value
    # Raw SMS text feeds semantic candidate retrieval
    kwargs = match_service.match.await_args.kwargs
    assert kwargs["query_text"] == "I want $150 this week"
    # Reply is deferred until after the orchestrator commits
    assert len(ctx.post_commit_actions) == 1
    mock_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_work_goal_handler_passes_deadline_to_repo():
    """Extracted target_deadline reaches the repository as a parsed datetime."""
    from datetime import UTC, datetime

    handler, wr_repo, _, _ = _make_handler()
    mock_session = AsyncMock()
    ctx = _make_ctx(mock_session, target_deadline="2026-07-25T23:59:59")

    await handler.handle(ctx)

    wg_create = wr_repo.create.await_args.args[1]
    assert wg_create.target_deadline == datetime(2026, 7, 25, 23, 59, 59, tzinfo=UTC)


@pytest.mark.asyncio
async def test_work_goal_handler_sends_match_reply_post_commit():
    """Deferred action sends the formatted match SMS to the goal sender."""
    from src.matches.formatter import format_match_sms

    handler, _, _, mock_twilio = _make_handler()
    mock_session = AsyncMock()
    ctx = _make_ctx(mock_session)

    await handler.handle(ctx)
    with patch(
        "src.sms.outbound.asyncio.to_thread", new=AsyncMock(return_value=None)
    ) as mock_to_thread:
        for action in ctx.post_commit_actions:
            await action()

    mock_to_thread.assert_awaited_once()
    kwargs = mock_to_thread.await_args.kwargs
    assert kwargs["to"] == "+13125551234"
    assert kwargs["from_"] == "+10000000000"
    expected_body = format_match_sms(
        MatchResult(jobs=[], work_goal=MagicMock(), total_earnings=0, is_partial=True)
    )
    assert kwargs["body"] == expected_body


@pytest.mark.asyncio
async def test_work_goal_handler_reply_failure_does_not_raise():
    """Twilio failure in the deferred reply is logged, not propagated."""
    handler, _, _, mock_twilio = _make_handler()
    mock_twilio.messages.create.side_effect = Exception("Twilio down")
    mock_session = AsyncMock()
    ctx = _make_ctx(mock_session)

    logged_errors = []

    class CapturingLogger:
        def error(self, event, **kw):
            logged_errors.append(event)

        def info(self, *a, **kw):
            pass

        def warning(self, *a, **kw):
            pass

    await handler.handle(ctx)
    with patch("src.pipeline.handlers.work_goal.log", CapturingLogger()):
        for action in ctx.post_commit_actions:
            await action()

    assert any("match_reply_failed" in e for e in logged_errors)
