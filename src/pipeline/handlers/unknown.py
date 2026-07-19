import asyncio

import structlog
from opentelemetry import trace as otel_trace

from src.extraction.constants import UNKNOWN_REPLY_TEXT
from src.extraction.schemas import ExtractionResult
from src.extraction.service import ExtractionService
from src.pipeline.constants import (
    OTEL_ATTR_MESSAGING_DESTINATION,
    OTEL_ATTR_MESSAGING_SYSTEM,
)
from src.pipeline.context import PipelineContext
from src.pipeline.handlers.base import MessageHandler
from src.sms.constants import MessageType
from src.sms.service import hash_phone

tracer = otel_trace.get_tracer(__name__)
log = structlog.get_logger()


class UnknownMessageHandler(MessageHandler):
    message_type = MessageType.UNKNOWN

    def __init__(self, twilio_client, extraction_service: ExtractionService):
        self._twilio_client = twilio_client
        self._extraction_service = extraction_service

    def can_handle(self, result: ExtractionResult) -> bool:
        # Catch-all — must be last in chain (per D-04)
        return True

    async def handle(self, ctx: PipelineContext) -> None:
        settings = self._extraction_service.settings
        message_sid = ctx.message_sid
        from_number = ctx.from_number

        async def send_unknown_reply() -> None:
            with tracer.start_as_current_span("twilio.send_sms") as span:
                span.set_attribute(OTEL_ATTR_MESSAGING_SYSTEM, "twilio")
                span.set_attribute(
                    OTEL_ATTR_MESSAGING_DESTINATION, hash_phone(from_number)
                )
                try:
                    await asyncio.to_thread(
                        self._twilio_client.messages.create,
                        to=from_number,
                        from_=settings.sms.from_number,
                        body=UNKNOWN_REPLY_TEXT,
                    )
                except Exception as exc:
                    log.error(
                        "unknown_reply_failed",
                        message_sid=message_sid,
                        error=str(exc),
                    )
                    return
            log.info(
                "unknown_reply_sent",
                message_sid=message_sid,
                to_hash=hash_phone(from_number),
            )

        ctx.run_after_commit(send_unknown_reply)
