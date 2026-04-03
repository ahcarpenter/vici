import structlog
from datetime import UTC, datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.jobs.models import Job
from src.jobs.schemas import JobCreate
from src.repository import BaseRepository


class JobRepository(BaseRepository):
    async def create(self, session: AsyncSession, job_create: JobCreate) -> Job:
        ideal_dt = None
        if job_create.ideal_datetime:
            try:
                ideal_dt = datetime.fromisoformat(str(job_create.ideal_datetime))
                if ideal_dt.tzinfo is None:
                    ideal_dt = ideal_dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                structlog.get_logger().warning(
                    "job.ideal_datetime_parse_failed",
                    raw_value=str(job_create.ideal_datetime),
                )
                ideal_dt = None

        job = Job(
            user_id=job_create.user_id,
            message_id=job_create.message_id,
            description=job_create.description,
            location=job_create.location,
            pay_rate=job_create.pay_rate,
            pay_type=job_create.pay_type,
            estimated_duration_hours=job_create.estimated_duration_hours,
            raw_duration_text=job_create.raw_duration_text,
            ideal_datetime=ideal_dt,
            raw_datetime_text=job_create.raw_datetime_text,
            inferred_timezone=job_create.inferred_timezone,
            datetime_flexible=job_create.datetime_flexible,
            created_at=datetime.now(UTC),
        )
        return await self._persist(session, job)
