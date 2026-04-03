from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog
from opentelemetry import trace as otel_trace
from sqlalchemy import text
from sqlmodel import select
from temporalio import activity
from temporalio.exceptions import ApplicationError

from src.config import get_settings
from src.database import get_sessionmaker
from src.extraction.utils import write_job_embedding
from src.pipeline.constants import OTEL_ATTR_MESSAGE_ID, OTEL_ATTR_PHONE_HASH
from src.sms.models import Message
from src.sms.service import hash_phone

tracer = otel_trace.get_tracer(__name__)

if TYPE_CHECKING:
    from src.pipeline.orchestrator import PipelineOrchestrator

# Module-level singletons set by worker.run_worker() before the worker starts
_orchestrator: "PipelineOrchestrator | None" = None
_openai_client = None


@dataclass
class ProcessMessageInput:
    message_sid: str
    from_number: str
    body: str


@activity.defn
async def process_message_activity(input: ProcessMessageInput) -> str:
    """Wire SMS body through PipelineOrchestrator."""
    logger = structlog.get_logger()
    message_sid = input.message_sid
    from_number = input.from_number
    body = input.body

    logger.info("message.received consumed", message_sid=message_sid)

    phone_hash = hash_phone(from_number)

    with tracer.start_as_current_span("temporal.process_message") as span:
        span.set_attribute("temporal.event", "message.received")
        span.set_attribute("temporal.function", "process-message")
        span.set_attribute(OTEL_ATTR_MESSAGE_ID, message_sid)
        span.set_attribute(OTEL_ATTR_PHONE_HASH, phone_hash)

        # Resolve message_id and user_id from the DB row written by the webhook handler
        async with get_sessionmaker()() as session:
            row = await session.execute(
                select(Message).where(Message.message_sid == message_sid)
            )
            message = row.scalar_one_or_none()
            if message is None:
                raise ApplicationError(
                    f"process_message: message row not found for sid={message_sid}",
                    non_retryable=True,
                )

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


@activity.defn
async def handle_process_message_failure_activity(
    input: ProcessMessageInput,
) -> None:
    """Called after retries are exhausted. Logs error and increments failure counter."""
    logger = structlog.get_logger()
    logger.error(
        "process_message: permanent failure after retries exhausted",
        message_sid=input.message_sid,
    )
    from src.metrics import pipeline_failures_total

    pipeline_failures_total.labels(function="process-message").inc()


@activity.defn
async def sync_pinecone_queue_activity() -> str:
    """Sweeps pinecone_sync_queue for pending rows and upserts to Pinecone."""
    logger = structlog.get_logger()

    with tracer.start_as_current_span("temporal.sync_pinecone_queue") as span:
        logger.info("sync-pinecone-queue: starting sweep")

        async with get_sessionmaker()() as session:
            result = await session.execute(
                text(
                    "SELECT q.id, q.job_id, j.description, u.phone_hash "
                    "FROM pinecone_sync_queue q "
                    "JOIN job j ON j.id = q.job_id "
                    'JOIN "user" u ON u.id = j.user_id '
                    "WHERE q.status = 'pending' LIMIT 50"
                )
            )
            rows = result.mappings().all()

        logger.info("sync-pinecone-queue: rows fetched", count=len(rows))
        span.set_attribute("pinecone.rows_fetched", len(rows))

        failed = 0
        for row in rows:
            try:
                await write_job_embedding(
                    job_id=row["job_id"],
                    description=row["description"],
                    phone_hash=row["phone_hash"],
                    openai_client=_openai_client,
                    settings=get_settings(),
                )
                async with get_sessionmaker()() as session:
                    await session.execute(
                        text(
                            "UPDATE pinecone_sync_queue"
                            " SET status='success' WHERE id=:id"
                        ),
                        {"id": row["id"]},
                    )
                    await session.commit()
            except Exception as exc:
                failed += 1
                span.add_event("row_upsert_failed", {"job_id": str(row["job_id"])})
                logger.warning(
                    "sync-pinecone-queue: upsert failed",
                    job_id=row["job_id"],
                    error=str(exc),
                )
                async with get_sessionmaker()() as session:
                    await session.execute(
                        text(
                            "UPDATE pinecone_sync_queue SET status='failed', "
                            "retry_count=retry_count+1 WHERE id=:id"
                        ),
                        {"id": row["id"]},
                    )
                    await session.commit()

        span.set_attribute("pinecone.rows_failed", failed)
        if failed:
            logger.warning(
                "sync-pinecone-queue: sweep completed with failures",
                processed=len(rows),
                failed=failed,
            )
        logger.info("sync-pinecone-queue: sweep complete", processed=len(rows))

    return "ok"
