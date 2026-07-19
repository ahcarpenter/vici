"""
Integration test: work goal end-to-end flow.

NOTE: The full pipeline integration test was removed when Inngest was
replaced by Temporal
(Phase 02.9). The pipeline logic is covered by tests/temporal/test_activities.py.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


@pytest.mark.skip(
    reason="Full pipeline integration test needs rewrite for Temporal worker"
)
async def test_full_pipeline_work_goal():
    """Placeholder — rewrite for Temporal in a future phase."""
    pass


@pytest.mark.asyncio
async def test_work_goal_handler_emits_span():
    """WorkGoalHandler emits pipeline.handle_work_goal span."""
    import src.pipeline.handlers.work_goal as wg_module
    from src.extraction.schemas import ExtractionResult, WorkGoalExtraction
    from src.pipeline.constants import OTEL_ATTR_MESSAGE_ID, OTEL_ATTR_WORK_GOAL_USER_ID
    from src.pipeline.context import PipelineContext
    from src.pipeline.handlers.work_goal import WorkGoalHandler

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    test_tracer = provider.get_tracer("test")
    original_tracer = wg_module.tracer
    wg_module.tracer = test_tracer

    try:
        mock_wr_repo = AsyncMock()
        mock_wr = MagicMock()
        mock_wr.id = 77
        mock_wr_repo.create = AsyncMock(return_value=mock_wr)

        mock_audit_repo = AsyncMock()
        mock_audit_repo.write = AsyncMock(return_value=None)

        handler = WorkGoalHandler(
            work_goal_repo=mock_wr_repo,
            audit_repo=mock_audit_repo,
        )

        worker = WorkGoalExtraction(target_earnings=150.0, target_timeframe="this week")
        result = ExtractionResult(message_type="work_goal", work_goal=worker)

        test_message_sid = "SMwgtest"
        test_user_id = 42

        mock_session = AsyncMock()

        ctx = PipelineContext(
            session=mock_session,
            result=result,
            sms_text="I want $150 this week",
            phone_hash="hashwg",
            message_id=5,
            user_id=test_user_id,
            message_sid=test_message_sid,
            from_number="+13125551234",
        )

        await handler.handle(ctx)

        spans = exporter.get_finished_spans()
        span_names = [s.name for s in spans]
        assert "pipeline.handle_work_goal" in span_names, (
            f"Expected pipeline.handle_work_goal span. Got: {span_names}"
        )

        wg_span = next(s for s in spans if s.name == "pipeline.handle_work_goal")
        attrs = dict(wg_span.attributes)
        assert attrs.get(OTEL_ATTR_MESSAGE_ID) == test_message_sid
        assert attrs.get(OTEL_ATTR_WORK_GOAL_USER_ID) == str(test_user_id)

        # Flush-only contract: the handler must not commit
        mock_session.commit.assert_not_awaited()
    finally:
        wg_module.tracer = original_tracer
        exporter.shutdown()
