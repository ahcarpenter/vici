import json
from datetime import UTC, date, datetime

import structlog
from braintrust import init_logger, wrap_openai
from openai import APIStatusError, AsyncOpenAI, RateLimitError
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from src.extraction.constants import GPT_MODEL
from src.extraction.prompts import SYSTEM_PROMPT
from src.extraction.schemas import ExtractionResult

_bt_logger = init_logger(project="vici")  # module-level singleton

log = structlog.get_logger()


class ExtractionService:
    def __init__(self, settings):
        self._client = wrap_openai(
            AsyncOpenAI(api_key=settings.extraction.openai_api_key, max_retries=0)
        )
        self._settings = settings

    async def process(
        self,
        sms_text: str,
        phone_hash: str,
        message_id: int | None = None,
        user_id: int | None = None,
        session: AsyncSession | None = None,
        message_sid: str | None = None,
    ) -> ExtractionResult:
        from src.extraction.pinecone_client import write_job_embedding
        from src.jobs.repository import JobRepository
        from src.jobs.schemas import JobCreate
        from src.work_requests.repository import WorkRequestRepository
        from src.work_requests.schemas import WorkRequestCreate

        user_message = f"Today is {date.today().isoformat()}. Message: {sms_text}"
        result = await self._call_with_retry(user_message)

        log.info(
            "gpt_classified",
            message_type=result.message_type,
            phone_hash=phone_hash,
        )

        # If no session provided, return result without storage (backward compat)
        if session is None or message_id is None or user_id is None:
            return result

        # Use message_sid for audit_log (fall back to str(message_id) if not provided)
        audit_sid = message_sid or str(message_id)

        await self._write_audit(
            session, message_id, audit_sid, "gpt_classified",
            {"message_type": result.message_type},
        )

        if result.message_type == "job_posting" and result.job:
            job_create = JobCreate(
                user_id=user_id,
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
            # Create job row (commits internally)
            job = await JobRepository.create(session, job_create)

            # Update message.message_type atomically
            await session.execute(
                sa_text(
                    "UPDATE message SET message_type = 'job_posting' WHERE id = :mid"
                ),
                {"mid": message_id},
            )
            await session.commit()

            await self._write_audit(
                session, message_id, audit_sid, "job_created", {"job_id": job.id}
            )

            # Fire-and-forget Pinecone upsert
            try:
                await write_job_embedding(
                    job_id=job.id,
                    description=result.job.description,
                    phone_hash=phone_hash,
                    openai_client=self._client,
                    settings=self._settings,
                )
            except Exception as e:
                log.error("pinecone_write_failed", job_id=job.id, error=str(e))
                await self._write_audit(
                    session, message_id, audit_sid, "pinecone_write_failed",
                    {"job_id": job.id, "error": str(e)},
                )
                await self._enqueue_pinecone_sync(session, job.id)

        elif result.message_type == "worker_goal" and result.worker:
            wr_create = WorkRequestCreate(
                user_id=user_id,
                message_id=message_id,
                target_earnings=result.worker.target_earnings,
                target_timeframe=result.worker.target_timeframe,
                raw_sms=sms_text,
            )
            wr = await WorkRequestRepository.create(session, wr_create)
            await session.execute(
                sa_text(
                    "UPDATE message SET message_type = 'worker_goal' WHERE id = :mid"
                ),
                {"mid": message_id},
            )
            await session.commit()
            await self._write_audit(
                session, message_id, audit_sid, "work_request_created",
                {"work_request_id": wr.id},
            )

        else:  # unknown or GPT refusal
            await session.execute(
                sa_text(
                    "UPDATE message SET message_type = 'unknown' WHERE id = :mid"
                ),
                {"mid": message_id},
            )
            await session.commit()

        return result

    @retry(
        retry=retry_if_exception_type((RateLimitError, APIStatusError)),
        stop=stop_after_attempt(4),
        wait=wait_random_exponential(multiplier=1, min=1, max=60),
    )
    async def _call_with_retry(self, user_message: str) -> ExtractionResult:
        completion = await self._client.beta.chat.completions.parse(
            model=GPT_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format=ExtractionResult,
        )
        return completion.choices[0].message.parsed

    async def _write_audit(
        self,
        session: AsyncSession,
        message_id: int,
        message_sid: str,
        event: str,
        detail: dict,
    ) -> None:
        await session.execute(
            sa_text(
                "INSERT INTO audit_log (message_sid, message_id, event, detail, created_at) "
                "VALUES (:sid, :mid, :event, :detail, :created_at)"
            ),
            {
                "sid": message_sid,
                "mid": message_id,
                "event": event,
                "detail": json.dumps(detail),
                "created_at": datetime.now(UTC),
            },
        )
        await session.commit()

    async def _enqueue_pinecone_sync(
        self, session: AsyncSession, job_id: int
    ) -> None:
        await session.execute(
            sa_text(
                "INSERT INTO pinecone_sync_queue (job_id, status, attempts, created_at) "
                "VALUES (:job_id, 'pending', 0, :created_at)"
            ),
            {"job_id": job_id, "created_at": datetime.now(UTC)},
        )
        await session.commit()
