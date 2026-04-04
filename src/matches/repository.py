from datetime import UTC, datetime

import sqlalchemy.exc
from sqlalchemy.ext.asyncio import AsyncSession

from src.matches.models import Match
from src.repository import BaseRepository


class MatchRepository(BaseRepository):
    async def persist_matches(
        self, session: AsyncSession, job_ids: list[int], work_goal_id: int
    ) -> None:
        """
        Persist (job_id, work_goal_id) pairs to match table.
        Silently skips duplicates using IntegrityError catch -- cross-dialect compatible
        with both PostgreSQL (production) and SQLite (tests).
        Per D-10: UNIQUE(job_id, work_goal_id) -- on conflict, skip.
        Does NOT use pg_insert().on_conflict_do_nothing() to avoid SQLite incompatibility.
        """
        for job_id in job_ids:
            try:
                match = Match(
                    job_id=job_id,
                    work_goal_id=work_goal_id,
                    created_at=datetime.now(UTC),
                )
                await self._persist(session, match)
            except sqlalchemy.exc.IntegrityError:
                await session.rollback()
