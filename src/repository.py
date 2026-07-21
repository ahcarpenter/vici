from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class BaseRepository:
    """Base class providing the shared flush-only persistence step.

    Deliberately not an ABC — it exists for code reuse, not as an interface;
    repositories that never insert may still extend it for uniformity.
    """

    async def _persist(self, session: AsyncSession, entity: T) -> T:
        """Add entity to session and flush. Caller owns the transaction."""
        session.add(entity)
        await session.flush()
        return entity
