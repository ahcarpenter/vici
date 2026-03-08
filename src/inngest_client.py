from functools import lru_cache
from typing import TYPE_CHECKING

import inngest
import structlog
from opentelemetry import trace as otel_trace
from sqlmodel import select

from src.config import get_settings
from src.database import get_sessionmaker
from src.sms.models import Message
from src.sms.service import hash_phone

tracer = otel_trace.get_tracer(__name__)

if TYPE_CHECKING:
    from src.extraction.orchestrator import PipelineOrchestrator

# Module-level orchestrator singleton set by lifespan in main.py
_orchestrator: "PipelineOrchestrator | None" = None


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
    """Wire SMS body through PipelineOrchestrator; orchestrator handles all pipeline logic."""
    logger = structlog.get_logger()
    data = ctx.event.data
    message_sid: str = data.get("message_sid", "")
    from_number: str = data.get("from_number", "")
    body: str = data.get("body", "")

    logger.info("message.received consumed", message_sid=message_sid)

    phone_hash = hash_phone(from_number)

    with tracer.start_as_current_span("inngest.process_message") as span:
        span.set_attribute("inngest.event", "message.received")
        span.set_attribute("inngest.function", "process-message")

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

            orchestrator = _orchestrator
            await orchestrator.run(
                session=session,
                sms_text=body,
                phone_hash=phone_hash,
                message_id=message_id,
                user_id=user_id,
                message_sid=message_sid,
                from_number=from_number,
            )

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
