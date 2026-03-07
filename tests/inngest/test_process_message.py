import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import inngest
import pytest

from src.extraction.schemas import (
    ExtractionResult,
    JobExtraction,
    UnknownMessage,
    WorkerExtraction,
)
from src.extraction.constants import UNKNOWN_REPLY_TEXT


class MockSettings:
    openai_api_key = "test-key"
    braintrust_api_key = "test-bt-key"
    twilio_account_sid = "ACtest"
    twilio_auth_token = "token"
    twilio_from_number = "+10000000000"
    pinecone_api_key = ""
    pinecone_index_host = ""


def _make_ctx(message_sid="SMtest", from_number="+13125551234", body="hello"):
    """Build a minimal Inngest Context object for process_message tests."""
    event = MagicMock(spec=inngest.Event)
    event.data = {
        "message_sid": message_sid,
        "from_number": from_number,
        "body": body,
    }
    ctx = MagicMock(spec=inngest.Context)
    ctx.event = event
    return ctx


def _make_message_row(message_id=1, user_id=42):
    """Minimal Message ORM stub."""
    row = MagicMock()
    row.id = message_id
    row.user_id = user_id
    return row


def _make_extraction_result(message_type: str) -> ExtractionResult:
    if message_type == "job_posting":
        job = JobExtraction(
            description="Mover needed",
            datetime_flexible=False,
            location="Chicago",
            pay_type="hourly",
        )
        return ExtractionResult(message_type="job_posting", job=job)
    elif message_type == "worker_goal":
        worker = WorkerExtraction(target_earnings=200.0, target_timeframe="today")
        return ExtractionResult(message_type="worker_goal", worker=worker)
    else:
        unknown = UnknownMessage(reason="Greeting only")
        return ExtractionResult(message_type="unknown", unknown=unknown)


@pytest.mark.asyncio
async def test_process_message_job():
    """Job classification: ExtractionService called, no Twilio SMS sent."""
    ctx = _make_ctx(body="Need a mover Saturday downtown Chicago $25/hr")
    mock_message = _make_message_row()
    extraction_result = _make_extraction_result("job_posting")

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_message))
    )
    mock_sessionmaker = MagicMock(return_value=MagicMock(
        __aenter__=AsyncMock(return_value=mock_session),
        __aexit__=AsyncMock(return_value=None),
    ))

    mock_service = AsyncMock()
    mock_service.process = AsyncMock(return_value=extraction_result)

    with (
        patch("src.inngest_client.get_settings", return_value=MockSettings()),
        patch("src.inngest_client.get_sessionmaker", return_value=mock_sessionmaker),
        patch("src.inngest_client.ExtractionService", return_value=mock_service),
        patch("src.inngest_client.TwilioClient") as mock_twilio,
    ):
        from src.inngest_client import process_message
        result = await process_message._handler(ctx)

    assert result == "ok"
    mock_service.process.assert_called_once()
    mock_twilio.return_value.messages.create.assert_not_called()


@pytest.mark.asyncio
async def test_process_message_worker():
    """Worker classification: ExtractionService called, no Twilio SMS sent."""
    ctx = _make_ctx(body="I need $200 today")
    mock_message = _make_message_row()
    extraction_result = _make_extraction_result("worker_goal")

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_message))
    )
    mock_sessionmaker = MagicMock(return_value=MagicMock(
        __aenter__=AsyncMock(return_value=mock_session),
        __aexit__=AsyncMock(return_value=None),
    ))

    mock_service = AsyncMock()
    mock_service.process = AsyncMock(return_value=extraction_result)

    with (
        patch("src.inngest_client.get_settings", return_value=MockSettings()),
        patch("src.inngest_client.get_sessionmaker", return_value=mock_sessionmaker),
        patch("src.inngest_client.ExtractionService", return_value=mock_service),
        patch("src.inngest_client.TwilioClient") as mock_twilio,
    ):
        from src.inngest_client import process_message
        result = await process_message._handler(ctx)

    assert result == "ok"
    mock_service.process.assert_called_once()
    mock_twilio.return_value.messages.create.assert_not_called()


@pytest.mark.asyncio
async def test_process_message_unknown_sends_sms():
    """Unknown classification: ExtractionService called, Twilio SMS sent with UNKNOWN_REPLY_TEXT."""
    ctx = _make_ctx(body="Hello", from_number="+13125551234")
    mock_message = _make_message_row()
    extraction_result = _make_extraction_result("unknown")

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_message))
    )
    mock_sessionmaker = MagicMock(return_value=MagicMock(
        __aenter__=AsyncMock(return_value=mock_session),
        __aexit__=AsyncMock(return_value=None),
    ))

    mock_service = AsyncMock()
    mock_service.process = AsyncMock(return_value=extraction_result)

    with (
        patch("src.inngest_client.get_settings", return_value=MockSettings()),
        patch("src.inngest_client.get_sessionmaker", return_value=mock_sessionmaker),
        patch("src.inngest_client.ExtractionService", return_value=mock_service),
        patch("src.inngest_client.TwilioClient") as mock_twilio_cls,
        patch("src.inngest_client.asyncio") as mock_asyncio,
    ):
        mock_asyncio.to_thread = AsyncMock(return_value=MagicMock(sid="SMreply"))
        from src.inngest_client import process_message
        result = await process_message._handler(ctx)

    assert result == "ok"
    mock_service.process.assert_called_once()
    # Confirm to_thread was called with Twilio messages.create
    mock_asyncio.to_thread.assert_called_once()
    call_kwargs = mock_asyncio.to_thread.call_args
    # First positional arg is the callable (client.messages.create)
    # Keyword args must include body=UNKNOWN_REPLY_TEXT and to="+13125551234"
    assert call_kwargs.kwargs.get("body") == UNKNOWN_REPLY_TEXT
    assert call_kwargs.kwargs.get("to") == "+13125551234"
