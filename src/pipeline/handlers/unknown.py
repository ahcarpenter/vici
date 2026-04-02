import asyncio

import structlog
from opentelemetry import trace as otel_trace
from sqlalchemy import text as sa_text

from src.extraction.constants import UNKNOWN_REPLY_TEXT
from src.extraction.schemas import ExtractionResult
from src.extraction.service import ExtractionService
from src.pipeline.context import PipelineContext
from src.pipeline.handlers.base import MessageHandler

tracer = otel_trace.get_tracer(__name__)
log = structlog.get_logger()


class UnknownMessageHandler(MessageHandler):
    def __init__(self, twilio_client, extraction_service: ExtractionService):
        self._twilio_client = twilio_client
        self._extraction_service = extraction_service

    def can_handle(self, result: ExtractionResult) -> bool:
        # Catch-all — must be last in chain (per D-04)
        return True

    async def handle(self, ctx: PipelineContext) -> None:
        await ctx.session.execute(
            sa_text("UPDATE message SET message_type = 'unknown' WHERE id = :mid"),
            {"mid": ctx.message_id},
        )
        await ctx.session.commit()

        settings = self._extraction_service.settings
        with tracer.start_as_current_span("twilio.send_sms") as span:
            span.set_attribute("messaging.system", "twilio")
            span.set_attribute("messaging.destination", ctx.from_number)
            await asyncio.to_thread(
                self._twilio_client.messages.create,
                to=ctx.from_number,
                from_=settings.sms.from_number,
                body=UNKNOWN_REPLY_TEXT,
            )
        log.info(
            "unknown_reply_sent",
            message_sid=ctx.message_sid,
            to=ctx.from_number,
        )
