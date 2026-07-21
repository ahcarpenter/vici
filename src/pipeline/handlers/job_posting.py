import json
from typing import Protocol

import structlog
from opentelemetry import trace as otel_trace

from src.extraction.constants import MessageType
from src.extraction.repository import PineconeSyncQueueRepository
from src.extraction.schemas import ExtractionResult
from src.jobs.constants import PayType
from src.jobs.repository import JobRepository
from src.jobs.schemas import JobCreate
from src.money import dollars_to_cents
from src.observability import (
    OTEL_ATTR_DB_OPERATION,
    OTEL_ATTR_DB_SYSTEM,
    OTEL_ATTR_DB_VECTOR_JOB_ID,
)
from src.pipeline.context import PipelineContext
from src.pipeline.handlers.base import MessageHandler
from src.sms.audit_repository import AuditLogRepository
from src.sms.constants import AuditEvent

tracer = otel_trace.get_tracer(__name__)
log = structlog.get_logger()


class JobEmbeddingWriter(Protocol):
    """Port for writing a job embedding to the vector index.

    The handler owns this contract; composition (main.py) binds the OpenAI
    client and settings so the handler never touches either.
    """

    async def __call__(
        self, *, job_id: int, description: str, phone_hash: str
    ) -> None: ...


class JobPostingHandler(MessageHandler):
    message_type = MessageType.JOB_POSTING

    def __init__(
        self,
        job_repo: JobRepository,
        audit_repo: AuditLogRepository,
        job_embedding_writer: JobEmbeddingWriter,
        sync_queue_repo: PineconeSyncQueueRepository,
    ):
        self._job_repo = job_repo
        self._audit_repo = audit_repo
        self._job_embedding_writer = job_embedding_writer
        self._sync_queue_repo = sync_queue_repo

    def can_handle(self, result: ExtractionResult) -> bool:
        return result.message_type == MessageType.JOB_POSTING and result.job is not None

    async def handle(self, ctx: PipelineContext) -> None:
        extracted = ctx.result.job
        assert extracted is not None  # guaranteed by can_handle
        job_create = JobCreate(
            message_id=ctx.message_id,
            description=extracted.description,
            location=extracted.location,
            pay_rate=dollars_to_cents(extracted.pay_rate)
            if extracted.pay_rate is not None
            else None,
            pay_type=PayType(extracted.pay_type),
            # str from the LLM — JobCreate parses it, nulling junk values.
            ideal_datetime=extracted.ideal_datetime,  # type: ignore[arg-type]
            estimated_duration_hours=extracted.estimated_duration_hours,
            raw_duration_text=extracted.raw_duration_text,
            raw_datetime_text=extracted.raw_datetime_text,
            inferred_timezone=extracted.inferred_timezone,
            datetime_flexible=extracted.datetime_flexible,
        )
        job = await self._job_repo.create(ctx.session, job_create)
        assert job.id is not None  # DB-assigned on flush

        await self._audit_repo.write(
            ctx.session,
            ctx.message_sid,
            AuditEvent.JOB_CREATED,
            detail=json.dumps({"job_id": job.id}),
            message_id=ctx.message_id,
        )

        # Capture plain values now — the ORM row must not be touched post-commit.
        job_id = job.id
        description = extracted.description
        phone_hash = ctx.phone_hash
        session = ctx.session
        sync_queue_repo = self._sync_queue_repo
        writer = self._job_embedding_writer

        async def upsert_embedding() -> None:
            try:
                with tracer.start_as_current_span("pinecone.upsert") as span:
                    span.set_attribute(OTEL_ATTR_DB_SYSTEM, "pinecone")
                    span.set_attribute(OTEL_ATTR_DB_OPERATION, "upsert")
                    span.set_attribute(OTEL_ATTR_DB_VECTOR_JOB_ID, str(job_id))
                    await writer(
                        job_id=job_id,
                        description=description,
                        phone_hash=phone_hash,
                    )
            except Exception as e:
                log.error("pinecone_write_failed", job_id=job_id, error=str(e))
                # Runs after the orchestrator's commit — the session is idle,
                # so this enqueue is its own small transaction.
                try:
                    await sync_queue_repo.enqueue(session, job_id)
                    await session.commit()
                except Exception as queue_exc:
                    log.error(
                        "pinecone_queue_insert_failed",
                        job_id=job_id,
                        error=str(queue_exc),
                    )
                    await session.rollback()

        ctx.run_after_commit(upsert_embedding)
