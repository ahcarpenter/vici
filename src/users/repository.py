from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from src.users.models import User


class UserRepository:
    @staticmethod
    async def get_or_create(
        session: AsyncSession, phone_hash: str, phone_e164: Optional[str] = None
    ) -> User:
        """Upsert a user row by phone_hash. Returns the User ORM object."""
        params = {
            "phone_hash": phone_hash,
            "phone_e164": phone_e164,
            "created_at": datetime.now(UTC),
        }
        result = await session.execute(
            text(
                """
                INSERT INTO "user" (phone_hash, phone_e164, created_at)
                VALUES (:phone_hash, :phone_e164, :created_at)
                ON CONFLICT (phone_hash) DO NOTHING
                RETURNING id, phone_hash, phone_e164, created_at
                """
            ),
            params,
        )
        row = result.mappings().first()
        if row is not None:
            return User(
                id=row["id"],
                phone_hash=row["phone_hash"],
                phone_e164=row["phone_e164"],
                created_at=row["created_at"],
            )

        fetch = await session.execute(select(User).where(User.phone_hash == phone_hash))
        return fetch.scalar_one()
