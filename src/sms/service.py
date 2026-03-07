import hashlib
import json
from datetime import UTC, datetime

import inngest as inngest_module
from opentelemetry.propagate import inject as otel_inject
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from src.sms.constants import MAX_MESSAGES_PER_WINDOW
from src.sms.models import AuditLog, Message, RateLimit
from src.users.models import User


def hash_phone(e164_number: str) -> str:
    """SHA-256 hash of E.164 phone number. Twilio From is already E.164."""
    return hashlib.sha256(e164_number.encode()).hexdigest()


async def check_idempotency(session: AsyncSession, message_sid: str) -> bool:
    """Return True if this MessageSid has already been processed."""
    result = await session.execute(
        select(Message).where(Message.message_sid == message_sid)
    )
    return result.first() is not None


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


async def enforce_rate_limit(session: AsyncSession, user_id: int) -> bool:
    """
    Upsert a count for (user_id, window_start). Returns True if the
    count AFTER the upsert exceeds MAX_MESSAGES_PER_WINDOW (caller should
    return empty TwiML 200). Returns False if within the limit.
    """
    window = datetime.now(UTC).replace(second=0, microsecond=0)

    await session.execute(
        text(
            """
            INSERT INTO rate_limit (user_id, window_start, count)
            VALUES (:user_id, :window_start, 1)
            ON CONFLICT ON CONSTRAINT uq_rate_limit_user_window
            DO UPDATE SET count = rate_limit.count + 1
            """
        ),
        {"user_id": user_id, "window_start": window},
    )

    result = await session.execute(
        select(RateLimit).where(
            RateLimit.user_id == user_id,
            RateLimit.window_start == window,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    return row.count > MAX_MESSAGES_PER_WINDOW


async def write_inbound_message(
    session: AsyncSession,
    message_sid: str,
    user_id: int,
    body: str,
) -> Message:
    """Persist the message record. Returns the Message object."""
    row = Message(
        message_sid=message_sid,
        user_id=user_id,
        body=body,
    )
    session.add(row)
    await session.flush()
    return row


async def write_audit_log(
    session: AsyncSession,
    message_sid: str,
    event: str,
    detail: str | None = None,
    message_id: int | None = None,
) -> None:
    """Append an audit_log row for this message_sid."""
    row = AuditLog(
        message_sid=message_sid,
        event=event,
        detail=detail,
        message_id=message_id,
    )
    session.add(row)
    await session.flush()


async def emit_message_received_event(
    client: inngest_module.Inngest,
    message_sid: str,
    from_number: str,
    body: str,
) -> None:
    """
    Fire-and-forget: emit message.received event to Inngest.
    Injects W3C traceparent so the Inngest function can continue the trace.
    """
    carrier: dict = {}
    otel_inject(carrier)  # {"traceparent": "00-<trace_id>-<span_id>-01"} or {}

    await client.send(
        inngest_module.Event(
            name="message.received",
            data={
                "message_sid": message_sid,
                "from_number": from_number,
                "body": body,
                "otel": carrier,
            },
        )
    )
