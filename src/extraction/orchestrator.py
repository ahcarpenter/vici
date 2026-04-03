import asyncio
import json
from datetime import UTC, datetime

import structlog
from opentelemetry import trace as otel_trace
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_sessionmaker
from src.extraction.constants import UNKNOWN_REPLY_TEXT
from src.extraction.schemas import ExtractionResult
from src.extraction.service import ExtractionService
from src.jobs.repository import JobRepository
from src.jobs.schemas import JobCreate
from src.sms.audit_repository import AuditLogRepository
from src.sms.repository import MessageRepository
from src.work_requests.repository import WorkRequestRepository
from src.work_requests.schemas import WorkRequestCreate

tracer = otel_trace.get_tracer(__name__)
log = structlog.get_logger()


class PipelineOrchestrator:
    def __init__(
        self,
        extraction_service: ExtractionService,
        job_repo: JobRepository,
        work_request_repo: WorkRequestRepository,
        message_repo: MessageRepository,
        audit_repo: AuditLogRepository,
        pinecone_client,
        twilio_client,
    ):
        self._extraction_service = extraction_service
        self._job_repo = job_repo
        self._work_request_repo = work_request_repo
        self._message_repo = message_repo
        self._audit_repo = audit_repo
        self._pinecone_client = pinecone_client
        self._twilio_client = twilio_client

    async def run(
        self,
        session: AsyncSession,
        sms_text: str,
        phone_hash: str,
        message_id: int,
        user_id: int,
        message_sid: str,
        from_number: str,
    ) -> ExtractionResult:
        # 1. Classify via GPT (no session)
        result = await self._extraction_service.process(sms_text, phone_hash)

        # 2. Log classification audit
        await self._audit_repo.write(
            session,
            message_sid,
            "gpt_classified",
            detail=json.dumps({"message_type": result.message_type}),
            message_id=message_id,
        )

        # 3. Branch by message_type
        if result.message_type == "job_posting" and result.job:
            job_create = JobCreate(
                message_id=message_id,
                description=result.job.description,
                location=result.job.location,
                pay_rate=result.job.pay_rate,
                pay_type=result.job.pay_type,
                estimated_duration_hours=result.job.estimated_duration_hours,
                raw_duration_text=result.job.raw_duration_text,
                ideal_datetime=result.job.ideal_datetime,
                raw_datetime_text=result.job.raw_datetime_text,
                inferred_timezone=result.job.inferred_timezone,
                datetime_flexible=result.job.datetime_flexible,
                raw_sms=sms_text,
            )
            job = await self._job_repo.create(session, job_create)

            await session.execute(
                sa_text(
                    "UPDATE message SET message_type = 'job_posting' WHERE id = :mid"
                ),
                {"mid": message_id},
            )
            await self._audit_repo.write(
                session,
                message_sid,
                "job_created",
                detail=json.dumps({"job_id": job.id}),
                message_id=message_id,
            )

            # Single commit for this branch (before Pinecone — failure should not roll back)
            await session.commit()

            # Fire-and-forget Pinecone upsert (after commit)
            try:
                with tracer.start_as_current_span("pinecone.upsert") as span:
                    span.set_attribute("db.system", "pinecone")
                    span.set_attribute("db.operation", "upsert")
                    span.set_attribute("db.vector.job_id", str(job.id))
                    await self._pinecone_client(
                        job_id=job.id,
                        description=result.job.description,
                        phone_hash=phone_hash,
                        openai_client=self._extraction_service._client,
                        settings=self._extraction_service._settings,
                    )
            except Exception as e:
                log.error("pinecone_write_failed", job_id=job.id, error=str(e))
                # Enqueue retry in a separate session so the main commit is not affected
                async with get_sessionmaker()() as s2:
                    await s2.execute(
                        sa_text(
                            "INSERT INTO pinecone_sync_queue (job_id, status, attempts, created_at) "
                            "VALUES (:job_id, 'pending', 0, :created_at)"
                        ),
                        {"job_id": job.id, "created_at": datetime.now(UTC)},
                    )
                    await s2.commit()

        elif result.message_type == "worker_goal" and result.worker:
            wr_create = WorkRequestCreate(
                message_id=message_id,
                target_earnings=result.worker.target_earnings,
                target_timeframe=result.worker.target_timeframe,
                raw_sms=sms_text,
            )
            wr = await self._work_request_repo.create(session, wr_create)

            await session.execute(
                sa_text(
                    "UPDATE message SET message_type = 'worker_goal' WHERE id = :mid"
                ),
                {"mid": message_id},
            )
            await self._audit_repo.write(
                session,
                message_sid,
                "work_request_created",
                detail=json.dumps({"work_request_id": wr.id}),
                message_id=message_id,
            )

            # Single commit for worker branch
            await session.commit()

        else:  # unknown
            await session.execute(
                sa_text(
                    "UPDATE message SET message_type = 'unknown' WHERE id = :mid"
                ),
                {"mid": message_id},
            )
            await session.commit()

            # Send Twilio unknown reply (synchronous client wrapped in thread)
            settings = self._extraction_service._settings
            with tracer.start_as_current_span("twilio.send_sms") as span:
                span.set_attribute("messaging.system", "twilio")
                span.set_attribute("messaging.destination", from_number)
                await asyncio.to_thread(
                    self._twilio_client.messages.create,
                    to=from_number,
                    from_=settings.sms.from_number,
                    body=UNKNOWN_REPLY_TEXT,
                )
            log.info("unknown_reply_sent", message_sid=message_sid, to=from_number)

        return result
