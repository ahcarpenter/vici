import json
from datetime import UTC, datetime

import structlog
from opentelemetry import trace as otel_trace
from sqlalchemy import text as sa_text

from src.database import get_sessionmaker
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

tracer = otel_trace.get_tracer(__name__)
log = structlog.get_logger()


class JobPostingHandler(MessageHandler):
    def __init__(
        self,
        job_repo: JobRepository,
        audit_repo: AuditLogRepository,
        pinecone_client,
        extraction_service: ExtractionService,
    ):
        self._job_repo = job_repo
        self._audit_repo = audit_repo
        self._pinecone_client = pinecone_client
        self._extraction_service = extraction_service

    def can_handle(self, result: ExtractionResult) -> bool:
        return result.message_type == "job_posting" and result.job is not None

    async def handle(self, ctx: PipelineContext) -> None:
        result = ctx.result
        job_create = JobCreate(
            user_id=ctx.user_id,
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
            raw_sms=ctx.sms_text,
        )
        job = await self._job_repo.create(ctx.session, job_create)

        await ctx.session.execute(
            sa_text("UPDATE message SET message_type = 'job_posting' WHERE id = :mid"),
            {"mid": ctx.message_id},
        )
        await self._audit_repo.write(
            ctx.session,
            ctx.message_sid,
            "job_created",
            detail=json.dumps({"job_id": job.id}),
            message_id=ctx.message_id,
        )

        await ctx.session.commit()

        # Fire-and-forget Pinecone upsert (after commit)
        try:
            with tracer.start_as_current_span("pinecone.upsert") as span:
                span.set_attribute(OTEL_ATTR_DB_SYSTEM, "pinecone")
                span.set_attribute(OTEL_ATTR_DB_OPERATION, "upsert")
                span.set_attribute(OTEL_ATTR_DB_VECTOR_JOB_ID, str(job.id))
                await self._pinecone_client(
                    job_id=job.id,
                    description=result.job.description,
                    phone_hash=ctx.phone_hash,
                    openai_client=self._extraction_service.openai_client,
                    settings=self._extraction_service.settings,
                )
        except Exception as e:
            log.error("pinecone_write_failed", job_id=job.id, error=str(e))
            try:
                async with get_sessionmaker()() as s2:
                    await s2.execute(
                        sa_text(
                            "INSERT INTO pinecone_sync_queue "
                            "(job_id, status, attempts, created_at) "
                            "VALUES (:job_id, 'pending', 0, :created_at)"
                        ),
                        {"job_id": job.id, "created_at": datetime.now(UTC)},
                    )
                    await s2.commit()
            except Exception as queue_exc:
                log.error(
                    "pinecone_queue_insert_failed",
                    job_id=job.id,
                    error=str(queue_exc),
                )
