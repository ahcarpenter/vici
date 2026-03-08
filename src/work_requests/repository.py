from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.work_requests.models import WorkRequest
from src.work_requests.schemas import WorkRequestCreate


class WorkRequestRepository:
    @staticmethod
    async def create(
        session: AsyncSession, wr_create: WorkRequestCreate
    ) -> WorkRequest:
        wr = WorkRequest(
            user_id=wr_create.user_id,
            message_id=wr_create.message_id,
            target_earnings=wr_create.target_earnings,
            target_timeframe=wr_create.target_timeframe,
            created_at=datetime.now(UTC),
        )
        session.add(wr)
        await session.flush()
        return wr
