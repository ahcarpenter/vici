from functools import lru_cache

import inngest
import structlog

from src.config import get_settings


@lru_cache(maxsize=1)
def get_inngest_client() -> inngest.Inngest:
    settings = get_settings()
    return inngest.Inngest(
        app_id="vici",
        is_production=not settings.inngest_dev,
    )


@get_inngest_client().create_function(
    fn_id="process-message",
    trigger=inngest.TriggerEvent(event="message.received"),
)
async def process_message(ctx: inngest.Context) -> str:
    """Phase 1 stub. Full pipeline wired in Phase 4."""
    logger = structlog.get_logger()
    logger.info(
        "message.received consumed",
        message_sid=ctx.event.data.get("message_sid"),
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

