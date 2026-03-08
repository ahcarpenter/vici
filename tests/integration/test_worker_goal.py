"""
Integration test: worker goal end-to-end flow.

Webhook → Message row created → Inngest event simulated → orchestrator.run() called →
WorkRequest row written to DB → message.message_type == 'worker_goal'.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select

import src.inngest_client as ic
from src.database import get_session
from src.extraction.orchestrator import PipelineOrchestrator
from src.extraction.schemas import ExtractionResult, WorkerExtraction
from src.inngest_client import get_inngest_client
from src.jobs.repository import JobRepository
from src.main import create_app
from src.sms.audit_repository import AuditLogRepository
from src.sms.models import Message
from src.sms.repository import MessageRepository
from src.work_requests.models import WorkRequest
from src.work_requests.repository import WorkRequestRepository


def _make_ctx(message_sid: str, from_number: str = "+13125551234", body: str = "I need $200 today"):
    import inngest
    event = MagicMock(spec=inngest.Event)
    event.data = {"message_sid": message_sid, "from_number": from_number, "body": body}
    ctx = MagicMock(spec=inngest.Context)
    ctx.event = event
    return ctx


@pytest.mark.asyncio
async def test_full_pipeline_worker_goal(test_engine, async_session):
    """POST /webhook/sms → process_message → WorkRequest row in DB, message.message_type='worker_goal'."""
    app = create_app()

    async def override_get_session():
        yield async_session

    app.dependency_overrides[get_session] = override_get_session

    from src.extraction.service import ExtractionService

    mock_extraction_service = MagicMock(spec=ExtractionService)
    mock_extraction_service._settings = MagicMock()
    mock_extraction_service._settings.sms.from_number = "+10000000000"
    mock_extraction_service._client = MagicMock()

    extraction_result = ExtractionResult(
        message_type="worker_goal",
        worker=WorkerExtraction(target_earnings=200.0, target_timeframe="today"),
    )
    mock_extraction_service.process = AsyncMock(return_value=extraction_result)

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

    original_orchestrator = ic._orchestrator
    ic._orchestrator = orchestrator
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

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
                    "MessageSid": "SM_integration_worker_001",
                    "From": "+13125551234",
                    "Body": "I need $200 today",
                    "AccountSid": "AC_test",
                }
                response = await client.post(
                    "/webhook/sms",
                    data=form,
                    headers={"X-Twilio-Signature": "valid"},
                )
                assert response.status_code == 200

            ctx = _make_ctx(
                message_sid="SM_integration_worker_001",
                from_number="+13125551234",
                body="I need $200 today",
            )
            from src.inngest_client import process_message
            result = await process_message._handler(ctx)
            assert result == "ok"

        await async_session.commit()
        msg_result = await async_session.execute(
            select(Message).where(Message.message_sid == "SM_integration_worker_001")
        )
        message = msg_result.scalar_one_or_none()
        assert message is not None
        assert message.message_type == "worker_goal"

        wr_result = await async_session.execute(
            select(WorkRequest).where(WorkRequest.message_id == message.id)
        )
        work_request = wr_result.scalar_one_or_none()
        assert work_request is not None
        assert work_request.target_earnings == 200.0

    finally:
        ic._orchestrator = original_orchestrator
        app.dependency_overrides.clear()
