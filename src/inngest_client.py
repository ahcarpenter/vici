import asyncio
from functools import lru_cache

import inngest
import structlog
from sqlmodel import select
from twilio.rest import Client as TwilioClient

from src.config import get_settings
from src.database import get_sessionmaker
from src.extraction.constants import UNKNOWN_REPLY_TEXT
from src.extraction.service import ExtractionService
from src.sms.models import Message
from src.sms.service import hash_phone


@lru_cache(maxsize=1)
def get_inngest_client() -> inngest.Inngest:
    settings = get_settings()
    return inngest.Inngest(
        app_id="vici",
        is_production=not settings.inngest_dev,
        event_api_base_url=settings.inngest_base_url,
    )


@get_inngest_client().create_function(
    fn_id="process-message",
    trigger=inngest.TriggerEvent(event="message.received"),
)
async def process_message(ctx: inngest.Context) -> str:
    """Wire SMS body through ExtractionService; send reply if message cannot be classified."""
    logger = structlog.get_logger()
    data = ctx.event.data
    message_sid: str = data.get("message_sid", "")
    from_number: str = data.get("from_number", "")
    body: str = data.get("body", "")

    logger.info("message.received consumed", message_sid=message_sid)

    settings = get_settings()
    phone_hash = hash_phone(from_number)

    # Resolve message_id and user_id from the DB row written by the webhook handler
    async with get_sessionmaker()() as session:
        row = await session.execute(
            select(Message).where(Message.message_sid == message_sid)
        )
        message = row.scalar_one_or_none()
        if message is None:
            logger.error("process_message: message row not found", message_sid=message_sid)
            return "ok"

        message_id = message.id
        user_id = message.user_id

        service = ExtractionService(settings)
        result = await service.process(
            sms_text=body,
            phone_hash=phone_hash,
            message_id=message_id,
            user_id=user_id,
            session=session,
            message_sid=message_sid,
        )

    if result.message_type == "unknown":
        twilio_client = TwilioClient(settings.sms.account_sid, settings.sms.auth_token)
        await asyncio.to_thread(
            twilio_client.messages.create,
            to=from_number,
            from_=settings.sms.from_number,
            body=UNKNOWN_REPLY_TEXT,
        )
        logger.info("unknown_reply_sent", message_sid=message_sid, to=from_number)

    return "ok"


@get_inngest_client().create_function(
    fn_id="sync-pinecone-queue",
    trigger=inngest.TriggerCron(cron="*/5 * * * *"),
)
async def sync_pinecone_queue(ctx: inngest.Context) -> str:
    """Phase 2 stub. Sweeps pinecone_sync_queue for pending rows. Full retry logic deferred."""
    logger = structlog.get_logger()
    logger.info("sync-pinecone-queue: stub run")
    return "ok"
