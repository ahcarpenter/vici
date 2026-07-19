from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from src.extraction.constants import SyncStatus
from src.extraction.models import PineconeSyncQueue
from src.jobs.models import Job
from src.repository import BaseRepository
from src.sms.models import Message
from src.users.models import User


@dataclass(frozen=True)
class PendingJobEmbedding:
    """A claimed sync-queue entry joined with what the embedding upsert needs."""

    entry: PineconeSyncQueue
    description: Optional[str]
    phone_hash: str


class PineconeSyncQueueRepository(BaseRepository):
    async def claim_pending(
        self, session: AsyncSession, limit: int
    ) -> list[PendingJobEmbedding]:
        """Lock and return pending entries with the job description and the
        poster's phone_hash (job -> message -> user traversal, via the model).

        Row locks (FOR UPDATE SKIP LOCKED) are held until the caller commits,
        so concurrent sweeps skip entries already being processed.
        """
        stmt = (
            select(PineconeSyncQueue, Job.description, User.phone_hash)
            .join(Job, Job.id == PineconeSyncQueue.job_id)
            .join(Message, Message.id == Job.message_id)
            .join(User, User.id == Message.user_id)
            .where(PineconeSyncQueue.status == SyncStatus.PENDING)
            .order_by(PineconeSyncQueue.id)
            .limit(limit)
            .with_for_update(skip_locked=True, of=PineconeSyncQueue)
        )
        rows = await session.execute(stmt)
        return [
            PendingJobEmbedding(entry=entry, description=description, phone_hash=ph)
            for entry, description, ph in rows.all()
        ]

    async def mark_synced(
        self, session: AsyncSession, entry: PineconeSyncQueue
    ) -> None:
        """Flush-only — caller owns the transaction."""
        entry.status = SyncStatus.SYNCED
        await self._persist(session, entry)

    async def mark_failed(
        self, session: AsyncSession, entry: PineconeSyncQueue, error: str
    ) -> None:
        """Flush-only — caller owns the transaction."""
        entry.status = SyncStatus.FAILED
        entry.attempts += 1
        entry.last_error = error
        await self._persist(session, entry)
