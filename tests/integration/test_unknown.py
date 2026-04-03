"""
Integration / handler tests: unknown message type.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_unknown_twilio_failure_does_not_raise():
    """Twilio raises: UnknownMessageHandler.handle completes without propagating."""
    from twilio.base.exceptions import TwilioRestException

    from src.pipeline.context import PipelineContext
    from src.pipeline.handlers.unknown import UnknownMessageHandler

    mock_extraction_service = MagicMock()
    mock_extraction_service.settings.sms.from_number = "+10000000000"

    mock_twilio = MagicMock()
    mock_twilio.messages.create.side_effect = TwilioRestException(
        status=500, uri="/Messages"
    )

    handler = UnknownMessageHandler(
        twilio_client=mock_twilio,
        extraction_service=mock_extraction_service,
    )

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    ctx = MagicMock(spec=PipelineContext)
    ctx.message_id = 1
    ctx.message_sid = "SMtest"
    ctx.from_number = "+13125551234"
    ctx.session = mock_session

    logged_errors = []

    class CapturingLogger:
        def error(self, event, **kw):
            logged_errors.append(event)

        def info(self, *a, **kw):
            pass

        def warning(self, *a, **kw):
            pass

    with patch("src.pipeline.handlers.unknown.log", CapturingLogger()):
        # Should not raise
        await handler.handle(ctx)

    assert any("unknown_reply_failed" in e for e in logged_errors)


@pytest.mark.asyncio
async def test_webhook_missing_message_sid_returns_400(test_engine, async_session):
    """POST /webhook/sms with missing MessageSid returns HTTP 400."""
    from httpx import ASGITransport, AsyncClient

    from src.database import get_session
    from src.main import create_app

    app = create_app()

    async def override_get_session():
        yield async_session

    app.dependency_overrides[get_session] = override_get_session

    try:
        with patch("twilio.request_validator.RequestValidator.validate", return_value=True):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                form = {
                    "From": "+13125551234",
                    "Body": "Hello",
                    "AccountSid": "AC_test",
                }
                response = await client.post(
                    "/webhook/sms",
                    data=form,
                    headers={"X-Twilio-Signature": "valid"},
                )
                assert response.status_code == 400
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_webhook_missing_from_returns_400(test_engine, async_session):
    """POST /webhook/sms with missing From returns HTTP 400."""
    from httpx import ASGITransport, AsyncClient

    from src.database import get_session
    from src.main import create_app

    app = create_app()

    async def override_get_session():
        yield async_session

    app.dependency_overrides[get_session] = override_get_session

    try:
        with patch("twilio.request_validator.RequestValidator.validate", return_value=True):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                form = {
                    "MessageSid": "SMtest",
                    "Body": "Hello",
                    "AccountSid": "AC_test",
                }
                response = await client.post(
                    "/webhook/sms",
                    data=form,
                    headers={"X-Twilio-Signature": "valid"},
                )
                assert response.status_code == 400
    finally:
        app.dependency_overrides.clear()
