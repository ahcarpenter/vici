from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from src.repository import BaseRepository
from src.sms.constants import MAX_MESSAGES_PER_WINDOW
from src.sms.exceptions import DuplicateMessageSid, RateLimitExceeded
from src.sms.models import Message


class MessageRepository(BaseRepository):
    @staticmethod
    async def check_idempotency(session: AsyncSession, message_sid: str) -> None:
        """Raise DuplicateMessageSid if this message_sid has already been processed."""
        result = await session.execute(
            select(Message).where(Message.message_sid == message_sid)
        )
        if result.first() is not None:
            raise DuplicateMessageSid(message_sid)

    @staticmethod
    async def enforce_rate_limit(session: AsyncSession, user_id: int) -> int:
        """
        Upsert a count for (user_id, window). Raise RateLimitExceeded if over
        MAX_MESSAGES_PER_WINDOW. Returns current count if within limit.
        """
        # TODO: A migration to drop the UNIQUE constraint on (user_id, created_at)
        # in the rate_limit table is needed before deploying this rolling-window change.
        window = datetime.now(UTC) - timedelta(seconds=60)

        await session.execute(
            text(
                """
                INSERT INTO rate_limit (user_id, created_at, count)
                VALUES (:user_id, NOW(), 1)
                """
            ),
            {"user_id": user_id},
        )
        # Count messages in the last 60 seconds for this user.
        count_result = await session.execute(
            text(
                "SELECT COUNT(*) FROM rate_limit "
                "WHERE user_id = :user_id AND created_at >= :window"
            ),
            {"user_id": user_id, "window": window},
        )
        count = count_result.scalar_one()
        if count > MAX_MESSAGES_PER_WINDOW:
            raise RateLimitExceeded(f"user_id={user_id} count={count}")
        return count

    async def create(
        self,
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
        return await self._persist(session, message)
