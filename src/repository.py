from abc import ABC
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class BaseRepository(ABC):
    """Base class providing the Template Method _persist for flush-only repositories."""

    async def _persist(self, session: AsyncSession, entity: T) -> T:
        """Add entity to session and flush. Caller owns the transaction."""
        session.add(entity)
        await session.flush()
        return entity
