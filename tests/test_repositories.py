"""
Tests for MessageRepository and AuditLogRepository.
"""

from datetime import UTC, datetime, timedelta

import pytest

from src.sms.exceptions import DuplicateMessageSid, RateLimitExceeded
from src.sms.repository import MessageRepository

RATE_LIMIT_MAX = 5
RATE_LIMIT_WINDOW_SECONDS = 60


@pytest.mark.asyncio
async def test_check_idempotency_existing(async_session, make_message):
    """check_idempotency raises DuplicateMessageSid if message_sid already exists."""
    message = await make_message()
    with pytest.raises(DuplicateMessageSid):
        await MessageRepository().check_idempotency(async_session, message.message_sid)


@pytest.mark.asyncio
async def test_check_idempotency_new(async_session):
    """check_idempotency returns None for unknown message_sid (no raise)."""
    result = await MessageRepository().check_idempotency(
        async_session, "unknown-sid-xyz"
    )
    assert result is None


@pytest.mark.asyncio
async def test_enforce_rate_limit_under_limit(async_session, make_user):
    """enforce_rate_limit does not raise when under the window limit."""
    user = await make_user()
    # Should not raise
    await MessageRepository().enforce_rate_limit(
        async_session,
        user.id,
        max_messages=RATE_LIMIT_MAX,
        window_seconds=RATE_LIMIT_WINDOW_SECONDS,
    )


@pytest.mark.asyncio
async def test_enforce_rate_limit_over_limit(async_session, make_user):
    """enforce_rate_limit raises RateLimitExceeded after max calls."""
    user = await make_user()
    repo = MessageRepository()
    with pytest.raises(RateLimitExceeded):
        for _ in range(RATE_LIMIT_MAX + 1):
            await repo.enforce_rate_limit(
                async_session,
                user.id,
                max_messages=RATE_LIMIT_MAX,
                window_seconds=RATE_LIMIT_WINDOW_SECONDS,
            )


@pytest.mark.asyncio
async def test_enforce_rate_limit_respects_configured_max(async_session, make_user):
    """A smaller configured max trips the limit sooner."""
    user = await make_user()
    repo = MessageRepository()
    await repo.enforce_rate_limit(
        async_session, user.id, max_messages=1, window_seconds=60
    )
    with pytest.raises(RateLimitExceeded):
        await repo.enforce_rate_limit(
            async_session, user.id, max_messages=1, window_seconds=60
        )


@pytest.mark.asyncio
async def test_purge_rate_limit_entries(async_session, make_user):
    """purge_rate_limit_entries deletes only rows older than the cutoff."""
    from sqlmodel import select

    from src.sms.models import RateLimit

    user = await make_user()
    now = datetime.now(UTC)
    old_row = RateLimit(user_id=user.id, created_at=now - timedelta(hours=2))
    fresh_row = RateLimit(user_id=user.id, created_at=now)
    async_session.add(old_row)
    async_session.add(fresh_row)
    await async_session.flush()

    deleted = await MessageRepository().purge_rate_limit_entries(
        async_session, older_than=now - timedelta(hours=1)
    )
    assert deleted == 1

    remaining = (
        (
            await async_session.execute(
                select(RateLimit).where(RateLimit.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert [r.id for r in remaining] == [fresh_row.id]


@pytest.mark.asyncio
async def test_audit_log_write(async_session, make_message):
    """AuditLogRepository.write inserts a row that exists after caller commits."""
    from sqlmodel import select

    from src.sms.audit_repository import AuditLogRepository
    from src.sms.models import AuditLog

    message = await make_message()
    await AuditLogRepository().write(
        async_session,
        message_sid=message.message_sid,
        event="test_event",
        detail="test detail",
        message_id=message.id,
    )
    await async_session.commit()

    result = await async_session.execute(
        select(AuditLog).where(AuditLog.message_sid == message.message_sid)
    )
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.event == "test_event"
    assert row.detail == "test detail"
    assert row.message_id == message.id
