import structlog
from datetime import UTC, datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from src.jobs.models import Job
from src.jobs.schemas import JobCreate
from src.repository import BaseRepository

log = structlog.get_logger()


class JobRepository(BaseRepository):
    async def find_candidates_for_goal(self, session: AsyncSession) -> list[Job]:
        """
        Returns all available jobs with computable earnings.
        Logs a structlog warning for each excluded job with job_id and reason.
        Exclusion rules (per D-03, D-04, D-06, D-06a):
          - status != 'available' (filtered in SQL)
          - pay_type == 'unknown' (filtered in SQL)
          - pay_rate is NULL (logged + excluded)
          - pay_type == 'hourly' and estimated_duration_hours is NULL (logged + excluded)
        """
        stmt = (
            select(Job)
            .where(Job.status == "available")
            .where(Job.pay_type != "unknown")
        )
        result = await session.execute(stmt)
        raw_jobs = list(result.scalars().all())

        candidates = []
        for job in raw_jobs:
            if job.pay_rate is None:
                log.warning("match.job_excluded", job_id=job.id, reason="null_pay_rate")
                continue
            if job.pay_type == "hourly" and job.estimated_duration_hours is None:
                log.warning(
                    "match.job_excluded", job_id=job.id, reason="null_duration_hourly"
                )
                continue
            candidates.append(job)
        return candidates

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
