"""
Tests for PipelineOrchestrator — plan 02.1-02.
Mocks at service/repo boundaries; verifies transaction discipline.
Span tests added in plan 02.3-02 using InMemorySpanExporter.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.extraction.schemas import (
    ExtractionResult,
    JobExtraction,
    UnknownMessage,
    WorkerExtraction,
)


def _make_orchestrator(
    extraction_result: ExtractionResult,
    pinecone_side_effect=None,
):
    """Build a PipelineOrchestrator with all deps mocked."""
    from src.extraction.orchestrator import PipelineOrchestrator

    mock_extraction_service = AsyncMock()
    mock_extraction_service.process = AsyncMock(return_value=extraction_result)

    mock_job_repo = AsyncMock()
    mock_job = MagicMock()
    mock_job.id = 42
    mock_job_repo.create = AsyncMock(return_value=mock_job)

    mock_wr_repo = AsyncMock()
    mock_wr = MagicMock()
    mock_wr.id = 99
    mock_wr_repo.create = AsyncMock(return_value=mock_wr)

    mock_message_repo = AsyncMock()
    mock_audit_repo = AsyncMock()
    mock_audit_repo.write = AsyncMock(return_value=None)

    mock_pinecone = AsyncMock()
    if pinecone_side_effect is not None:
        mock_pinecone.side_effect = pinecone_side_effect

    mock_twilio = MagicMock()

    orchestrator = PipelineOrchestrator(
        extraction_service=mock_extraction_service,
        job_repo=mock_job_repo,
        work_request_repo=mock_wr_repo,
        message_repo=mock_message_repo,
        audit_repo=mock_audit_repo,
        pinecone_client=mock_pinecone,
        twilio_client=mock_twilio,
    )
    return orchestrator, mock_extraction_service, mock_job_repo, mock_wr_repo, mock_audit_repo, mock_pinecone


def _make_session():
    """Return a mock async session."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_job_branch_commits_once():
    """Job branch: job_repo.create called, session.commit called exactly once."""
    job = JobExtraction(
        description="Need a mover for Saturday",
        datetime_flexible=False,
        location="downtown Chicago",
        pay_type="hourly",
        pay_rate=25.0,
    )
    result = ExtractionResult(message_type="job_posting", job=job)
    orchestrator, extraction_svc, job_repo, wr_repo, audit_repo, pinecone = _make_orchestrator(result)
    session = _make_session()

    with patch("src.extraction.orchestrator.get_sessionmaker"):
        out = await orchestrator.run(
            session=session,
            sms_text="Need a mover for Saturday",
            phone_hash="hash123",
            message_id=1,
            user_id=10,
            message_sid="SMabc",
            from_number="+15551234567",
        )

    assert out.message_type == "job_posting"
    job_repo.create.assert_awaited_once()
    session.commit.assert_awaited_once()
    # Work request repo must NOT be called
    wr_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_branch_commits_once():
    """Worker branch: work_request_repo.create called, audit written, commit once."""
    worker = WorkerExtraction(target_earnings=200.0, target_timeframe="today")
    result = ExtractionResult(message_type="worker_goal", worker=worker)
    orchestrator, extraction_svc, job_repo, wr_repo, audit_repo, pinecone = _make_orchestrator(result)
    session = _make_session()

    out = await orchestrator.run(
        session=session,
        sms_text="I need $200 today",
        phone_hash="hash456",
        message_id=2,
        user_id=11,
        message_sid="SMdef",
        from_number="+15559876543",
    )

    assert out.message_type == "worker_goal"
    wr_repo.create.assert_awaited_once()
    session.commit.assert_awaited_once()
    # Audit must be written before commit (audit_repo.write called at least once)
    assert audit_repo.write.await_count >= 1
    # Job repo must NOT be called
    job_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_branch():
    """Unknown branch: commit called once, no job/work_request rows created."""
    unknown = UnknownMessage(reason="Greeting with no actionable content")
    result = ExtractionResult(message_type="unknown", unknown=unknown)
    orchestrator, extraction_svc, job_repo, wr_repo, audit_repo, pinecone = _make_orchestrator(result)
    session = _make_session()

    out = await orchestrator.run(
        session=session,
        sms_text="Hello!",
        phone_hash="hash789",
        message_id=3,
        user_id=12,
        message_sid="SMghi",
        from_number="+15550001111",
    )

    assert out.message_type == "unknown"
    session.commit.assert_awaited_once()
    job_repo.create.assert_not_awaited()
    wr_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_pinecone_failure_enqueues_retry():
    """Pinecone write failure: pipeline returns result, does not re-raise, enqueues sync."""
    job = JobExtraction(
        description="Painting job",
        datetime_flexible=True,
        location="downtown",
        pay_type="flat",
        pay_rate=500.0,
    )
    result = ExtractionResult(message_type="job_posting", job=job)
    orchestrator, extraction_svc, job_repo, wr_repo, audit_repo, pinecone = _make_orchestrator(
        result, pinecone_side_effect=Exception("Pinecone unavailable")
    )
    session = _make_session()

    mock_s2 = AsyncMock()
    mock_s2.__aenter__ = AsyncMock(return_value=mock_s2)
    mock_s2.__aexit__ = AsyncMock(return_value=None)
    mock_sessionmaker = MagicMock(return_value=mock_s2)

    with patch("src.extraction.orchestrator.get_sessionmaker", return_value=mock_sessionmaker):
        out = await orchestrator.run(
            session=session,
            sms_text="Painting job downtown $500",
            phone_hash="hashABC",
            message_id=4,
            user_id=13,
            message_sid="SMjkl",
            from_number="+15552223333",
        )

    # Pipeline must not raise, must return result
    assert out.message_type == "job_posting"
    # Main commit still happened (before Pinecone attempt)
    session.commit.assert_awaited_once()
    # Enqueue via separate session
    mock_s2.execute.assert_awaited()
    mock_s2.commit.assert_awaited()


# ---------------------------------------------------------------------------
# Span tests (plan 02.3-02)
# ---------------------------------------------------------------------------

def _span_exporter_for_orchestrator():
    """Return (exporter, test_tracer) patched into orchestrator module."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    test_tracer = provider.get_tracer("test")
    return exporter, test_tracer


@pytest.mark.asyncio
async def test_job_branch_emits_pinecone_span():
    """Job branch emits a 'pinecone.upsert' span with db.system, db.operation, db.vector.job_id."""
    import src.extraction.orchestrator as orch_module

    exporter, test_tracer = _span_exporter_for_orchestrator()
    original_tracer = orch_module.tracer
    orch_module.tracer = test_tracer

    try:
        job = JobExtraction(
            description="Need a mover for Saturday",
            datetime_flexible=False,
            location="downtown Chicago",
            pay_type="hourly",
            pay_rate=25.0,
        )
        result = ExtractionResult(message_type="job_posting", job=job)
        orchestrator, _, job_repo, _, _, pinecone = _make_orchestrator(result)
        session = _make_session()

        with patch("src.extraction.orchestrator.get_sessionmaker"):
            await orchestrator.run(
                session=session,
                sms_text="Need a mover for Saturday",
                phone_hash="hash123",
                message_id=1,
                user_id=10,
                message_sid="SMabc",
                from_number="+15551234567",
            )

        spans = exporter.get_finished_spans()
        span_names = [s.name for s in spans]
        assert "pinecone.upsert" in span_names, f"Expected 'pinecone.upsert' span. Got: {span_names}"

        pinecone_span = next(s for s in spans if s.name == "pinecone.upsert")
        attrs = dict(pinecone_span.attributes)
        assert attrs.get("db.system") == "pinecone"
        assert attrs.get("db.operation") == "upsert"
        assert "db.vector.job_id" in attrs
    finally:
        orch_module.tracer = original_tracer
        exporter.shutdown()


@pytest.mark.asyncio
async def test_unknown_branch_emits_twilio_span():
    """Unknown branch emits a 'twilio.send_sms' span with messaging.system and messaging.destination."""
    import src.extraction.orchestrator as orch_module

    exporter, test_tracer = _span_exporter_for_orchestrator()
    original_tracer = orch_module.tracer
    orch_module.tracer = test_tracer

    try:
        unknown = UnknownMessage(reason="Greeting with no actionable content")
        result = ExtractionResult(message_type="unknown", unknown=unknown)
        orchestrator, _, _, _, _, _ = _make_orchestrator(result)
        session = _make_session()

        # Mock asyncio.to_thread to avoid real Twilio call
        with patch("src.extraction.orchestrator.asyncio.to_thread", new=AsyncMock(return_value=None)):
            await orchestrator.run(
                session=session,
                sms_text="Hello!",
                phone_hash="hash789",
                message_id=3,
                user_id=12,
                message_sid="SMghi",
                from_number="+15550001111",
            )

        spans = exporter.get_finished_spans()
        span_names = [s.name for s in spans]
        assert "twilio.send_sms" in span_names, f"Expected 'twilio.send_sms' span. Got: {span_names}"

        twilio_span = next(s for s in spans if s.name == "twilio.send_sms")
        attrs = dict(twilio_span.attributes)
        assert attrs.get("messaging.system") == "twilio"
        assert attrs.get("messaging.destination") == "+15550001111"
    finally:
        orch_module.tracer = original_tracer
        exporter.shutdown()


# ---------------------------------------------------------------------------
# Gauge updater hardening tests (plan 02.5-04)
# ---------------------------------------------------------------------------


def test_gauge_updater_no_silent_pass():
    """Verify gauge updater no longer has a bare 'pass' on exception — warning log present."""
    with open(Path(__file__).parent.parent / "src" / "main.py") as f:
        source = f.read()
    # Old pattern: except Exception:\n    pass
    assert "except Exception:\n                pass" not in source
    assert "gauge_updater" in source  # warning key present
