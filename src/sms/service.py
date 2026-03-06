import hashlib
import json
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from sqlmodel import select
from src.sms.models import Phone, InboundMessage, RateLimit, AuditLog
from src.sms.constants import MAX_MESSAGES_PER_WINDOW


def hash_phone(e164_number: str) -> str:
    """SHA-256 hash of E.164 phone number. Twilio From is already E.164."""
    return hashlib.sha256(e164_number.encode()).hexdigest()


async def check_idempotency(session: AsyncSession, message_sid: str) -> bool:
    """Return True if this MessageSid has already been processed."""
    result = await session.execute(
        select(InboundMessage).where(InboundMessage.message_sid == message_sid)
    )
    return result.first() is not None


def _current_window_start() -> datetime:
    """Truncate current UTC time to the 1-minute bucket."""
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0, tzinfo=None)
    return now


async def enforce_rate_limit(session: AsyncSession, phone_hash: str) -> bool:
    """
    Upsert a count for (phone_hash, window_start). Returns True if the
    count AFTER the upsert exceeds MAX_MESSAGES_PER_WINDOW (caller should
    return empty TwiML 200). Returns False if within the limit.
    """
    window = _current_window_start()

    await session.execute(
        text(
            """
            INSERT INTO rate_limit (phone_hash, window_start, count)
            VALUES (:phone_hash, :window_start, 1)
            ON CONFLICT (phone_hash, window_start)
            DO UPDATE SET count = rate_limit.count + 1
            """
        ),
        {"phone_hash": phone_hash, "window_start": window},
    )
    await session.commit()

    # Read back the current count
    result = await session.execute(
        select(RateLimit).where(
            RateLimit.phone_hash == phone_hash,
            RateLimit.window_start == window,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    return row.count > MAX_MESSAGES_PER_WINDOW


async def register_phone(session: AsyncSession, phone_hash: str) -> None:
    """Insert a new phone identity if it does not exist. Idempotent."""
    await session.execute(
        text(
            """
            INSERT INTO phone (phone_hash, created_at)
            VALUES (:phone_hash, :created_at)
            ON CONFLICT (phone_hash) DO NOTHING
            """
        ),
        {"phone_hash": phone_hash, "created_at": datetime.utcnow()},
    )
    await session.commit()


async def write_audit_log(
    session: AsyncSession,
    message_sid: str,
    event: str,
    detail: str | None = None,
) -> None:
    """Append an audit_log row for this message_sid."""
    row = AuditLog(message_sid=message_sid, event=event, detail=detail)
    session.add(row)
    await session.commit()


async def write_inbound_message(
    session: AsyncSession,
    message_sid: str,
    phone_hash: str,
    body: str,
    raw_sms: dict,
) -> None:
    """Persist the inbound_message record. raw_sms stored as JSON string."""
    row = InboundMessage(
        message_sid=message_sid,
        phone_hash=phone_hash,
        body=body,
        raw_sms=json.dumps(raw_sms),
    )
    session.add(row)
    await session.commit()


import inngest as inngest_module  # noqa: E402
from opentelemetry.propagate import inject as otel_inject  # noqa: E402


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
