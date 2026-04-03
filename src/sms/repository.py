from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from src.sms.constants import MAX_MESSAGES_PER_WINDOW
from src.sms.exceptions import DuplicateMessageSid, RateLimitExceeded
from src.sms.models import Message
from src.users.models import User


class MessageRepository:
    @staticmethod
    async def check_idempotency(session: AsyncSession, message_sid: str) -> None:
        """Raise DuplicateMessageSid if this message_sid has already been processed."""
        result = await session.execute(
            select(Message).where(Message.message_sid == message_sid)
        )
        if result.first() is not None:
            raise DuplicateMessageSid(message_sid)

    @staticmethod
    async def get_or_create_user(session: AsyncSession, phone_hash: str) -> User:
        """Upsert a user row by phone_hash. Returns the User ORM object."""
        await session.execute(
            text(
                """
                INSERT INTO "user" (phone_hash, created_at)
                VALUES (:phone_hash, :created_at)
                ON CONFLICT (phone_hash) DO NOTHING
                """
            ),
            {"phone_hash": phone_hash, "created_at": datetime.now(UTC)},
        )
        result = await session.execute(
            select(User).where(User.phone_hash == phone_hash)
        )
        return result.scalar_one()

    @staticmethod
    async def enforce_rate_limit(session: AsyncSession, user_id: int) -> int:
        """
        Upsert a count for (user_id, window). Raise RateLimitExceeded if over
        MAX_MESSAGES_PER_WINDOW. Returns current count if within limit.
        """
        window = datetime.now(UTC).replace(second=0, microsecond=0)

        # Insert one row per event (rolling-window pattern — no upsert needed)
        await session.execute(
            text(
                "INSERT INTO rate_limit (user_id, created_at, count)"
                " VALUES (:user_id, :created_at, 1)"
            ),
            {"user_id": user_id, "created_at": window},
        )
        # Count all rows in the current window for this user
        count_result = await session.execute(
            text(
                "SELECT COUNT(*) FROM rate_limit"
                " WHERE user_id = :user_id"
                " AND created_at = :created_at"
            ),
            {"user_id": user_id, "created_at": window},
        )
        count = count_result.scalar_one()
        if count > MAX_MESSAGES_PER_WINDOW:
            raise RateLimitExceeded(f"user_id={user_id} count={count}")
        return count

    @staticmethod
    async def create(
        session: AsyncSession,
        message_sid: str,
        user_id: int,
        body: str,
    ) -> Message:
        """Persist the message record. Flush-only — caller owns the transaction."""
        message = Message(
            message_sid=message_sid,
            user_id=user_id,
            body=body,
        )
        session.add(message)
        await session.flush()
        return message
