from collections.abc import Sequence
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, or_, select

from src.jobs.constants import JobStatus, PayType
from src.jobs.models import Job
from src.jobs.schemas import JobCreate
from src.repository import BaseRepository
from src.sms.models import Message
from src.users.models import User

log = structlog.get_logger()

MAX_CANDIDATES: int = 500


class JobRepository(BaseRepository):
    def _eligibility_stmt(self, deadline: datetime | None):
        """
        Base SELECT for match-eligible jobs (D-03, D-04, D-06, D-06a).

        Deadline: a job is eligible when it has no ideal_datetime, is
        datetime-flexible, or is scheduled on/before the goal deadline.
        NULL datetime_flexible falls through via .is_(True).
        """
        stmt = (
            select(Job)
            .where(Job.status == JobStatus.AVAILABLE)
            .where(Job.pay_type != PayType.UNKNOWN)
        )
        if deadline is not None:
            # Normalize to UTC before binding: sqlite's bind processor drops
            # the offset without converting, so a non-UTC-aware param would
            # compare incorrectly against UTC-labeled stored values.
            deadline = deadline.astimezone(UTC)
            stmt = stmt.where(
                or_(
                    col(Job.ideal_datetime).is_(None),
                    col(Job.datetime_flexible).is_(True),
                    col(Job.ideal_datetime) <= deadline,
                )
            )
        return stmt

    def _computable_only(self, raw_jobs: list[Job]) -> list[Job]:
        """Drop jobs with incomputable earnings, logging job_id and reason."""
        candidates = []
        for job in raw_jobs:
            reason = job.pay_terms.incomputable_reason()
            if reason is not None:
                log.warning("match.job_excluded", job_id=job.id, reason=reason)
                continue
            candidates.append(job)
        return candidates

    async def find_candidates_for_goal(
        self, session: AsyncSession, deadline: datetime | None = None
    ) -> list[Job]:
        """
        Returns all available jobs with computable earnings, optionally
        eligible for the goal deadline.
        Logs a structlog warning for each earnings-excluded job with job_id
        and reason. Exclusion rules (per D-03, D-04, D-06, D-06a):
          - status != 'available' (filtered in SQL)
          - pay_type == 'unknown' (filtered in SQL)
          - scheduled after the deadline, unless flexible (filtered in SQL)
          - earnings incomputable per PayTerms (logged + excluded)
        """
        stmt = self._eligibility_stmt(deadline).limit(MAX_CANDIDATES)
        result = await session.execute(stmt)
        return self._computable_only(list(result.scalars().all()))

    async def find_candidates_by_ids(
        self,
        session: AsyncSession,
        job_ids: Sequence[int],
        deadline: datetime | None = None,
    ) -> list[Job]:
        """
        Eligibility-filter the given ids (same rules as find_candidates_for_goal)
        and return them in the caller's order (semantic rank). No MAX_CANDIDATES
        limit — the caller's top-K already bounds the set. Ids missing or
        ineligible in Postgres (stale index entries) silently drop out.
        """
        if not job_ids:
            return []
        stmt = self._eligibility_stmt(deadline).where(col(Job.id).in_(job_ids))
        result = await session.execute(stmt)
        jobs = self._computable_only(list(result.scalars().all()))
        by_id = {job.id: job for job in jobs}
        return [by_id[i] for i in job_ids if i in by_id]

    async def find_posters(
        self, session: AsyncSession, jobs: Sequence[Job]
    ) -> dict[int, User | None]:
        """
        Map job.id -> the User who posted it.

        The poster of a job is reached by identity traversal:
        job.message_id -> message.user_id -> user. This method is the single
        home for that traversal — do not re-derive it elsewhere.
        """
        message_ids = [j.message_id for j in jobs]
        stmt = (
            select(Message.id, User)
            .join(User, col(User.id) == col(Message.user_id))
            .where(col(Message.id).in_(message_ids))
        )
        rows = await session.execute(stmt)
        poster_by_message: dict[int, User] = {
            message_id: user for message_id, user in rows.all()
        }
        posters: dict[int, User | None] = {}
        for job in jobs:
            assert job.id is not None  # rows loaded from the DB
            posters[job.id] = poster_by_message.get(job.message_id)
        return posters

    async def create(self, session: AsyncSession, job_create: JobCreate) -> Job:
        # ideal_datetime is normalized (parsed, tz-aware or None) by JobCreate.
        job = Job(
            message_id=job_create.message_id,
            description=job_create.description,
            location=job_create.location,
            pay_rate=job_create.pay_rate,
            pay_type=job_create.pay_type,
            estimated_duration_hours=job_create.estimated_duration_hours,
            raw_duration_text=job_create.raw_duration_text,
            ideal_datetime=job_create.ideal_datetime,
            raw_datetime_text=job_create.raw_datetime_text,
            inferred_timezone=job_create.inferred_timezone,
            datetime_flexible=job_create.datetime_flexible,
            created_at=datetime.now(UTC),
        )
        return await self._persist(session, job)
