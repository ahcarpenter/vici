"""
Integration test: job posting end-to-end flow.

Webhook → Message row created → Inngest event simulated → orchestrator.run() called →
Job row written to DB → message.message_type == 'job_posting'.

External deps mocked: OpenAI (via ExtractionService.process), Pinecone, Twilio lifespan.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select

import src.inngest_client as ic
from src.database import get_session
from src.extraction.orchestrator import PipelineOrchestrator
from src.extraction.schemas import ExtractionResult, JobExtraction
from src.inngest_client import get_inngest_client
from src.jobs.models import Job
from src.jobs.repository import JobRepository
from src.main import create_app
from src.sms.audit_repository import AuditLogRepository
from src.sms.models import AuditLog, Message
from src.sms.repository import MessageRepository
from src.work_requests.repository import WorkRequestRepository


def _make_ctx(message_sid: str, from_number: str = "+13125551234", body: str = "Need a mover"):
    import inngest
    event = MagicMock(spec=inngest.Event)
    event.data = {"message_sid": message_sid, "from_number": from_number, "body": body}
    ctx = MagicMock(spec=inngest.Context)
    ctx.event = event
    return ctx


@pytest.mark.asyncio
async def test_full_pipeline_job_posting(test_engine, async_session):
    """POST /webhook/sms → process_message → Job row in DB, message.message_type='job_posting'."""
    # Build app
    app = create_app()

    # Override DB session to use test session
    async def override_get_session():
        yield async_session

    app.dependency_overrides[get_session] = override_get_session

    # Build a real orchestrator pointing at test session
    from unittest.mock import AsyncMock as AM

    from src.extraction.service import ExtractionService

    mock_extraction_service = MagicMock(spec=ExtractionService)
    mock_extraction_service._settings = MagicMock()
    mock_extraction_service._settings.sms.from_number = "+10000000000"
    mock_extraction_service._client = MagicMock()

    extraction_result = ExtractionResult(
        message_type="job_posting",
        job=JobExtraction(
            description="Need a mover Saturday",
            datetime_flexible=True,
            location="Chicago",
            pay_type="hourly",
        ),
    )
    mock_extraction_service.process = AM(return_value=extraction_result)

    # No-op Pinecone
    async def noop_pinecone(**kwargs):
        pass

    mock_twilio = MagicMock()

    orchestrator = PipelineOrchestrator(
        extraction_service=mock_extraction_service,
        job_repo=JobRepository,
        work_request_repo=WorkRequestRepository,
        message_repo=MessageRepository,
        audit_repo=AuditLogRepository,
        pinecone_client=noop_pinecone,
        twilio_client=mock_twilio,
    )

    # Override sessionmaker used by orchestrator's pinecone fallback
    original_orchestrator = ic._orchestrator
    ic._orchestrator = orchestrator

    from src import database as db_module
    original_get_sessionmaker = db_module.get_sessionmaker

    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    def patched_sessionmaker():
        return session_factory()

    try:
        with (
            patch("src.inngest_client.get_sessionmaker", return_value=lambda: session_factory()),
            patch("src.extraction.orchestrator.get_sessionmaker", return_value=lambda: session_factory()),
            patch("twilio.request_validator.RequestValidator.validate", return_value=True),
            patch.object(get_inngest_client(), "send", new_callable=AsyncMock),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                form = {
                    "MessageSid": "SM_integration_job_001",
                    "From": "+13125551234",
                    "Body": "Need a mover Saturday downtown Chicago $25/hr",
                    "AccountSid": "AC_test",
                }
                response = await client.post(
                    "/webhook/sms",
                    data=form,
                    headers={"X-Twilio-Signature": "valid"},
                )
                assert response.status_code == 200
                assert "<Response" in response.text

            # Simulate Inngest event processing
            ctx = _make_ctx(
                message_sid="SM_integration_job_001",
                from_number="+13125551234",
                body="Need a mover Saturday downtown Chicago $25/hr",
            )
            from src.inngest_client import process_message
            result = await process_message._handler(ctx)
            assert result == "ok"

        # Assert DB state
        await async_session.commit()
        msg_result = await async_session.execute(
            select(Message).where(Message.message_sid == "SM_integration_job_001")
        )
        message = msg_result.scalar_one_or_none()
        assert message is not None
        assert message.message_type == "job_posting"

        job_result = await async_session.execute(
            select(Job).where(Job.message_id == message.id)
        )
        job = job_result.scalar_one_or_none()
        assert job is not None
        assert job.description == "Need a mover Saturday"

        # Assert audit log entries
        audit_result = await async_session.execute(
            select(AuditLog).where(AuditLog.message_sid == "SM_integration_job_001")
        )
        audit_rows = audit_result.scalars().all()
        audit_events = {row.event for row in audit_rows}
        assert "gpt_classified" in audit_events
        assert "job_created" in audit_events

    finally:
        ic._orchestrator = original_orchestrator
        app.dependency_overrides.clear()
