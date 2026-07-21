from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from opentelemetry import trace as otel_trace
from sqlmodel import select
from temporalio import activity
from temporalio.exceptions import ApplicationError

from src.config import get_settings
from src.database import get_sessionmaker
from src.extraction.constants import PINECONE_SYNC_BATCH_SIZE
from src.extraction.repository import PineconeSyncQueueRepository
from src.extraction.utils import write_job_embedding
from src.observability import OTEL_ATTR_MESSAGE_ID, OTEL_ATTR_PHONE_HASH
from src.sms.constants import RATE_LIMIT_PURGE_RETENTION
from src.sms.models import Message
from src.sms.repository import MessageRepository
from src.sms.service import hash_phone

tracer = otel_trace.get_tracer(__name__)

if TYPE_CHECKING:
    from src.pipeline.orchestrator import PipelineOrchestrator

if TYPE_CHECKING:
    from openai import AsyncOpenAI

# Module-level singletons set by worker.run_worker() before the worker starts
_orchestrator: "PipelineOrchestrator | None" = None
_openai_client: "AsyncOpenAI | None" = None


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

            assert message.id is not None  # DB-assigned primary key
            message_id = message.id
            user_id = message.user_id

            orchestrator = _orchestrator
            if orchestrator is None:
                raise ApplicationError(
                    "process_message: worker not initialized (orchestrator unset)",
                    non_retryable=True,
                )
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
    """Sweeps pinecone_sync_queue for pending rows and upserts to Pinecone.

    One session for the whole sweep: claim_pending's row locks stay held while
    rows are processed, so concurrent sweeps skip them; the single commit at
    the end releases the locks. Pinecone upserts are idempotent by job id, so
    a crashed sweep that rolls back statuses is safe to re-run.
    """
    logger = structlog.get_logger()
    repo = PineconeSyncQueueRepository()

    openai_client = _openai_client
    if openai_client is None:
        raise ApplicationError(
            "sync_pinecone_queue: worker not initialized (openai client unset)",
            non_retryable=True,
        )

    with tracer.start_as_current_span("temporal.sync_pinecone_queue") as span:
        logger.info("sync-pinecone-queue: starting sweep")

        async with get_sessionmaker()() as session:
            pending = await repo.claim_pending(session, PINECONE_SYNC_BATCH_SIZE)

            logger.info("sync-pinecone-queue: rows fetched", count=len(pending))
            span.set_attribute("pinecone.rows_fetched", len(pending))

            failed = 0
            for row in pending:
                try:
                    if row.description is None:
                        raise ValueError("job has no description to embed")
                    await write_job_embedding(
                        job_id=row.entry.job_id,
                        description=row.description,
                        phone_hash=row.phone_hash,
                        openai_client=openai_client,
                        settings=get_settings(),
                    )
                    await repo.mark_synced(session, row.entry)
                except Exception as exc:
                    failed += 1
                    span.add_event(
                        "row_upsert_failed", {"job_id": str(row.entry.job_id)}
                    )
                    logger.warning(
                        "sync-pinecone-queue: upsert failed",
                        job_id=row.entry.job_id,
                        error=str(exc),
                    )
                    await repo.mark_failed(session, row.entry, error=str(exc))

            await session.commit()

        span.set_attribute("pinecone.rows_failed", failed)
        if failed:
            logger.warning(
                "sync-pinecone-queue: sweep completed with failures",
                processed=len(pending),
                failed=failed,
            )
        logger.info("sync-pinecone-queue: sweep complete", processed=len(pending))

    return "ok"


@activity.defn
async def purge_rate_limit_activity() -> str:
    """Deletes rate_limit rows older than the retention window.

    Rolling-window rate limiting inserts one row per admitted message; without
    this sweep the table grows without bound.
    """
    logger = structlog.get_logger()
    cutoff = datetime.now(UTC) - RATE_LIMIT_PURGE_RETENTION

    with tracer.start_as_current_span("temporal.purge_rate_limit"):
        async with get_sessionmaker()() as session:
            deleted = await MessageRepository().purge_rate_limit_entries(
                session, older_than=cutoff
            )
            await session.commit()

    logger.info("purge-rate-limit: purge complete", deleted=deleted)
    return "ok"
