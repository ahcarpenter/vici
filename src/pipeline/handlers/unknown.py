import structlog
from twilio.rest import Client as TwilioClient

from src.extraction.constants import UNKNOWN_REPLY_TEXT, MessageType
from src.extraction.schemas import ExtractionResult
from src.pipeline.context import PipelineContext
from src.pipeline.handlers.base import MessageHandler
from src.sms.outbound import send_sms
from src.sms.service import hash_phone

log = structlog.get_logger()


class UnknownMessageHandler(MessageHandler):
    message_type = MessageType.UNKNOWN

    # Catch-all — the orchestrator requires this handler to sit last in the chain.
    is_terminal = True

    def __init__(self, twilio_client: TwilioClient, from_number: str):
        self._twilio_client = twilio_client
        self._from_number = from_number

    def can_handle(self, result: ExtractionResult) -> bool:
        return True

    async def handle(self, ctx: PipelineContext) -> None:
        message_sid = ctx.message_sid
        from_number = ctx.from_number

        async def send_unknown_reply() -> None:
            try:
                await send_sms(
                    self._twilio_client,
                    to=from_number,
                    from_number=self._from_number,
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
