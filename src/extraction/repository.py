from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

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
    description: str | None
    phone_hash: str


class PineconeSyncQueueRepository(BaseRepository):
    async def enqueue(self, session: AsyncSession, job_id: int) -> PineconeSyncQueue:
        """Queue a job for a later embedding sync (outbox fallback).
        Flush-only — caller owns the transaction."""
        entry = PineconeSyncQueue(job_id=job_id, status=SyncStatus.PENDING)
        return await self._persist(session, entry)

    async def count_pending(self, session: AsyncSession) -> int:
        """Number of entries still waiting to sync (feeds the depth gauge)."""
        result = await session.execute(
            select(func.count())
            .select_from(PineconeSyncQueue)
            .where(PineconeSyncQueue.status == SyncStatus.PENDING)
        )
        return result.scalar_one()

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
            .join(Job, col(Job.id) == col(PineconeSyncQueue.job_id))
            .join(Message, col(Message.id) == col(Job.message_id))
            .join(User, col(User.id) == col(Message.user_id))
            .where(PineconeSyncQueue.status == SyncStatus.PENDING)
            .order_by(col(PineconeSyncQueue.id))
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
