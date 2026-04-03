from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.repository import BaseRepository
from src.work_goals.models import WorkGoal
from src.work_goals.schemas import WorkGoalCreate


class WorkGoalRepository(BaseRepository):
    async def create(
        self, session: AsyncSession, wg_create: WorkGoalCreate
    ) -> WorkGoal:
        wg = WorkGoal(
            user_id=wg_create.user_id,
            message_id=wg_create.message_id,
            target_earnings=wg_create.target_earnings,
            target_timeframe=wg_create.target_timeframe,
            created_at=datetime.now(UTC),
        )
        return await self._persist(session, wg)
