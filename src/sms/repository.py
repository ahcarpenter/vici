from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from src.extraction.constants import MessageType
from src.repository import BaseRepository
from src.sms.exceptions import DuplicateMessageSid, RateLimitExceeded
from src.sms.models import Message, RateLimit


class MessageRepository(BaseRepository):
    async def check_idempotency(self, session: AsyncSession, message_sid: str) -> None:
        """Raise DuplicateMessageSid if this message_sid has already been processed."""
        result = await session.execute(
            select(Message).where(Message.message_sid == message_sid)
        )
        if result.first() is not None:
            raise DuplicateMessageSid(message_sid)

    async def enforce_rate_limit(
        self,
        session: AsyncSession,
        user_id: int,
        *,
        max_messages: int,
        window_seconds: int,
    ) -> int:
        """
        Record this message and count the user's messages in the rolling window.
        Raise RateLimitExceeded when the count exceeds *max_messages*.
        Returns current count if within limit.
        """
        window = datetime.now(UTC) - timedelta(seconds=window_seconds)

        # Insert one row per event (rolling-window pattern — no upsert needed)
        await session.execute(
            text(
                """
                INSERT INTO rate_limit (user_id, created_at)
                VALUES (:user_id, :now)
                """
            ),
            {"user_id": user_id, "now": datetime.now(UTC)},
        )
        count_result = await session.execute(
            text(
                "SELECT COUNT(*) FROM rate_limit "
                "WHERE user_id = :user_id AND created_at >= :window"
            ),
            {"user_id": user_id, "window": window},
        )
        count = count_result.scalar_one()
        if count > max_messages:
            raise RateLimitExceeded(f"user_id={user_id} count={count}")
        return count

    async def purge_rate_limit_entries(
        self, session: AsyncSession, older_than: datetime
    ) -> int:
        """Delete rate_limit rows older than *older_than*. Returns rows deleted.
        Flush-only — caller owns the transaction."""
        result = await session.execute(
            delete(RateLimit).where(col(RateLimit.created_at) < older_than)
        )
        return cast(CursorResult[Any], result).rowcount

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

    async def record_classification(
        self,
        session: AsyncSession,
        message_id: int,
        message_type: MessageType,
        raw_gpt_response: str | None = None,
    ) -> None:
        """Record the pipeline's classification of a message.

        Classification is a Message lifecycle event owned by this domain —
        handlers must call this rather than updating the message table directly.
        Flush-only — caller owns the transaction.
        """
        await session.execute(
            update(Message)
            .where(col(Message.id) == message_id)
            .values(message_type=message_type, raw_gpt_response=raw_gpt_response)
        )
