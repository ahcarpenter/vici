from datetime import UTC, datetime, timezone
from typing import Optional, Sequence

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from src.jobs.constants import JobStatus, PayType
from src.jobs.models import Job
from src.jobs.schemas import JobCreate
from src.repository import BaseRepository
from src.sms.models import Message
from src.users.models import User

log = structlog.get_logger()

MAX_CANDIDATES: int = 500


class JobRepository(BaseRepository):
    async def find_candidates_for_goal(self, session: AsyncSession) -> list[Job]:
        """
        Returns all available jobs with computable earnings.
        Logs a structlog warning for each excluded job with job_id and reason.
        Exclusion rules (per D-03, D-04, D-06, D-06a):
          - status != 'available' (filtered in SQL)
          - pay_type == 'unknown' (filtered in SQL)
          - earnings incomputable per PayTerms (logged + excluded)
        """
        stmt = (
            select(Job)
            .where(Job.status == JobStatus.AVAILABLE)
            .where(Job.pay_type != PayType.UNKNOWN)
            .limit(MAX_CANDIDATES)
        )
        result = await session.execute(stmt)
        raw_jobs = list(result.scalars().all())

        candidates = []
        for job in raw_jobs:
            reason = job.pay_terms.incomputable_reason()
            if reason is not None:
                log.warning("match.job_excluded", job_id=job.id, reason=reason)
                continue
            candidates.append(job)
        return candidates

    async def find_posters(
        self, session: AsyncSession, jobs: Sequence[Job]
    ) -> dict[int, Optional[User]]:
        """
        Map job.id -> the User who posted it.

        The poster of a job is reached by identity traversal:
        job.message_id -> message.user_id -> user. This method is the single
        home for that traversal — do not re-derive it elsewhere.
        """
        message_ids = [j.message_id for j in jobs]
        stmt = (
            select(Message.id, User)
            .join(User, User.id == Message.user_id)
            .where(Message.id.in_(message_ids))
        )
        rows = await session.execute(stmt)
        poster_by_message = {message_id: user for message_id, user in rows.all()}
        return {job.id: poster_by_message.get(job.message_id) for job in jobs}

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
