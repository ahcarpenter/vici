"""
Integration test: unknown message type end-to-end flow.

Webhook → Message row created → Inngest event simulated → orchestrator.run() called →
message.message_type == 'unknown' → Twilio reply sent with UNKNOWN_REPLY_TEXT.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select

import src.inngest_client as ic
from src.database import get_session
from src.extraction.constants import UNKNOWN_REPLY_TEXT
from src.extraction.orchestrator import PipelineOrchestrator
from src.extraction.schemas import ExtractionResult, UnknownMessage
from src.inngest_client import get_inngest_client
from src.jobs.repository import JobRepository
from src.main import create_app
from src.pipeline.handlers.job_posting import JobPostingHandler
from src.pipeline.handlers.unknown import UnknownMessageHandler
from src.pipeline.handlers.worker_goal import WorkerGoalHandler
from src.sms.audit_repository import AuditLogRepository
from src.sms.models import Message
from src.work_requests.repository import WorkRequestRepository


def _make_ctx(message_sid: str, from_number: str = "+13125551234", body: str = "Hello"):
    import inngest
    event = MagicMock(spec=inngest.Event)
    event.data = {"message_sid": message_sid, "from_number": from_number, "body": body}
    ctx = MagicMock(spec=inngest.Context)
    ctx.event = event
    return ctx


@pytest.mark.asyncio
async def test_full_pipeline_unknown(test_engine, async_session):
    """POST /webhook/sms → process_message → message.message_type='unknown' → Twilio reply sent."""
    app = create_app()

    async def override_get_session():
        yield async_session

    app.dependency_overrides[get_session] = override_get_session

    from src.extraction.service import ExtractionService

    mock_extraction_service = MagicMock(spec=ExtractionService)
    mock_extraction_service.settings = MagicMock()
    mock_extraction_service.settings.sms.from_number = "+10000000000"
    mock_extraction_service.openai_client = MagicMock()

    extraction_result = ExtractionResult(
        message_type="unknown",
        unknown=UnknownMessage(reason="Greeting only"),
    )
    mock_extraction_service.process = AsyncMock(return_value=extraction_result)

    async def noop_pinecone(**kwargs):
        pass

    mock_twilio = MagicMock()
    mock_twilio_send = AsyncMock()

    job_repo = JobRepository()
    work_request_repo = WorkRequestRepository()
    audit_repo = AuditLogRepository()

    handlers = [
        JobPostingHandler(
            job_repo=job_repo,
            audit_repo=audit_repo,
            pinecone_client=noop_pinecone,
            extraction_service=mock_extraction_service,
        ),
        WorkerGoalHandler(
            work_request_repo=work_request_repo,
            audit_repo=audit_repo,
        ),
        UnknownMessageHandler(
            twilio_client=mock_twilio,
            extraction_service=mock_extraction_service,
        ),
    ]

    orchestrator = PipelineOrchestrator(
        extraction_service=mock_extraction_service,
        audit_repo=audit_repo,
        handlers=handlers,
    )

    original_orchestrator = ic._orchestrator
    ic._orchestrator = orchestrator
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    try:
        with (
            patch("src.inngest_client.get_sessionmaker", return_value=lambda: session_factory()),
            patch("src.pipeline.handlers.job_posting.get_sessionmaker", return_value=lambda: session_factory()),
            patch("twilio.request_validator.RequestValidator.validate", return_value=True),
            patch.object(get_inngest_client(), "send", new_callable=AsyncMock),
            patch("src.pipeline.handlers.unknown.asyncio.to_thread", mock_twilio_send),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                form = {
                    "MessageSid": "SM_integration_unknown_001",
                    "From": "+13125551234",
                    "Body": "Hello",
                    "AccountSid": "AC_test",
                }
                response = await client.post(
                    "/webhook/sms",
                    data=form,
                    headers={"X-Twilio-Signature": "valid"},
                )
                assert response.status_code == 200

            ctx = _make_ctx(
                message_sid="SM_integration_unknown_001",
                from_number="+13125551234",
                body="Hello",
            )
            from src.inngest_client import process_message
            result = await process_message._handler(ctx)
            assert result == "ok"

        await async_session.commit()
        msg_result = await async_session.execute(
            select(Message).where(Message.message_sid == "SM_integration_unknown_001")
        )
        message = msg_result.scalar_one_or_none()
        assert message is not None
        assert message.message_type == "unknown"

        # Verify Twilio was called with UNKNOWN_REPLY_TEXT
        mock_twilio_send.assert_called_once()
        call_kwargs = mock_twilio_send.call_args.kwargs
        assert call_kwargs.get("body") == UNKNOWN_REPLY_TEXT
        assert call_kwargs.get("to") == "+13125551234"

    finally:
        ic._orchestrator = original_orchestrator
        app.dependency_overrides.clear()
