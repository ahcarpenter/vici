"""
Integration / handler tests: unknown message type.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


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
async def test_unknown_handler_span_uses_hashed_phone():
    """UnknownMessageHandler.handle() emits twilio.send_sms span
    with hashed phone, not raw E.164."""
    import src.pipeline.handlers.unknown as unknown_module
    from src.pipeline.context import PipelineContext
    from src.pipeline.handlers.unknown import UnknownMessageHandler
    from src.sms.service import hash_phone

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    test_tracer = provider.get_tracer("test")
    original_tracer = unknown_module.tracer
    unknown_module.tracer = test_tracer

    try:
        mock_extraction_service = MagicMock()
        mock_extraction_service.settings.sms.from_number = "+10000000000"

        mock_twilio = MagicMock()

        handler = UnknownMessageHandler(
            twilio_client=mock_twilio,
            extraction_service=mock_extraction_service,
        )

        raw_phone = "+13125559999"
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        ctx = MagicMock(spec=PipelineContext)
        ctx.message_id = 1
        ctx.message_sid = "SMunknown"
        ctx.from_number = raw_phone
        ctx.session = mock_session

        with patch(
            "src.pipeline.handlers.unknown.asyncio.to_thread",
            new=AsyncMock(return_value=None),
        ):
            await handler.handle(ctx)

        spans = exporter.get_finished_spans()
        span_names = [s.name for s in spans]
        assert "twilio.send_sms" in span_names

        twilio_span = next(s for s in spans if s.name == "twilio.send_sms")
        attrs = dict(twilio_span.attributes)

        # PII fix: raw phone must not appear as any attribute value
        assert attrs.get("messaging.destination.name") is not None
        assert attrs.get("messaging.destination.name") != raw_phone
        assert attrs.get("messaging.destination.name") == hash_phone(raw_phone)

        # Deprecated attribute must be absent
        assert "messaging.destination" not in attrs
    finally:
        unknown_module.tracer = original_tracer
        exporter.shutdown()


@pytest.mark.asyncio
async def test_webhook_missing_message_sid_returns_400(async_session, client):
    """POST /webhook/sms with missing MessageSid returns HTTP 400."""
    with patch("twilio.request_validator.RequestValidator.validate", return_value=True):
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


@pytest.mark.asyncio
async def test_webhook_missing_from_returns_400(async_session, client):
    """POST /webhook/sms with missing From returns HTTP 400."""
    with patch("twilio.request_validator.RequestValidator.validate", return_value=True):
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
