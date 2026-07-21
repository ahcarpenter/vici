from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.repository import BaseRepository
from src.users.models import User


class UserRepository(BaseRepository):
    async def get_or_create(
        self,
        session: AsyncSession,
        phone_hash: str,
        phone_e164: str | None = None,
    ) -> User:
        """Upsert a user row by phone_hash. Returns the User ORM object.

        Backfills phone_e164 for existing rows that don't have one yet, so
        users created before E.164 capture gain a contact number on their
        next inbound message.
        """
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
                ON CONFLICT (phone_hash) DO UPDATE
                    SET phone_e164 = COALESCE("user".phone_e164, EXCLUDED.phone_e164)
                RETURNING id, phone_hash, phone_e164, created_at
                """
            ),
            params,
        )
        row = result.mappings().one()
        return User(
            id=row["id"],
            phone_hash=row["phone_hash"],
            phone_e164=row["phone_e164"],
            created_at=row["created_at"],
        )
