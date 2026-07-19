import json

import structlog
from opentelemetry import trace as otel_trace

from src.database import get_sessionmaker
from src.extraction.constants import SyncStatus
from src.extraction.models import PineconeSyncQueue
from src.extraction.schemas import ExtractionResult
from src.extraction.service import ExtractionService
from src.jobs.repository import JobRepository
from src.jobs.schemas import JobCreate
from src.money import dollars_to_cents
from src.pipeline.constants import (
    OTEL_ATTR_DB_OPERATION,
    OTEL_ATTR_DB_SYSTEM,
    OTEL_ATTR_DB_VECTOR_JOB_ID,
)
from src.pipeline.context import PipelineContext
from src.pipeline.handlers.base import MessageHandler
from src.sms.audit_repository import AuditLogRepository
from src.sms.constants import AuditEvent, MessageType

tracer = otel_trace.get_tracer(__name__)
log = structlog.get_logger()


class JobPostingHandler(MessageHandler):
    message_type = MessageType.JOB_POSTING

    def __init__(
        self,
        job_repo: JobRepository,
        audit_repo: AuditLogRepository,
        job_embedding_writer,
        extraction_service: ExtractionService,
    ):
        self._job_repo = job_repo
        self._audit_repo = audit_repo
        self._job_embedding_writer = job_embedding_writer
        self._extraction_service = extraction_service

    def can_handle(self, result: ExtractionResult) -> bool:
        return result.message_type == MessageType.JOB_POSTING and result.job is not None

    async def handle(self, ctx: PipelineContext) -> None:
        result = ctx.result
        job_create = JobCreate(
            message_id=ctx.message_id,
            description=result.job.description,
            location=result.job.location,
            pay_rate=dollars_to_cents(result.job.pay_rate)
            if result.job.pay_rate is not None
            else None,
            pay_type=result.job.pay_type,
            estimated_duration_hours=result.job.estimated_duration_hours,
            raw_duration_text=result.job.raw_duration_text,
            ideal_datetime=result.job.ideal_datetime,
            raw_datetime_text=result.job.raw_datetime_text,
            inferred_timezone=result.job.inferred_timezone,
            datetime_flexible=result.job.datetime_flexible,
        )
        job = await self._job_repo.create(ctx.session, job_create)

        await self._audit_repo.write(
            ctx.session,
            ctx.message_sid,
            AuditEvent.JOB_CREATED,
            detail=json.dumps({"job_id": job.id}),
            message_id=ctx.message_id,
        )

        # Capture plain values now — the ORM row must not be touched post-commit.
        job_id = job.id
        description = result.job.description
        phone_hash = ctx.phone_hash

        async def upsert_embedding() -> None:
            try:
                with tracer.start_as_current_span("pinecone.upsert") as span:
                    span.set_attribute(OTEL_ATTR_DB_SYSTEM, "pinecone")
                    span.set_attribute(OTEL_ATTR_DB_OPERATION, "upsert")
                    span.set_attribute(OTEL_ATTR_DB_VECTOR_JOB_ID, str(job_id))
                    await self._job_embedding_writer(
                        job_id=job_id,
                        description=description,
                        phone_hash=phone_hash,
                        openai_client=self._extraction_service.openai_client,
                        settings=self._extraction_service.settings,
                    )
            except Exception as e:
                log.error("pinecone_write_failed", job_id=job_id, error=str(e))
                try:
                    async with get_sessionmaker()() as s2:
                        s2.add(
                            PineconeSyncQueue(job_id=job_id, status=SyncStatus.PENDING)
                        )
                        await s2.commit()
                except Exception as queue_exc:
                    log.error(
                        "pinecone_queue_insert_failed",
                        job_id=job_id,
                        error=str(queue_exc),
                    )

        ctx.run_after_commit(upsert_embedding)
