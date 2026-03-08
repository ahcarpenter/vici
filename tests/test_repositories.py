"""
Tests for MessageRepository and AuditLogRepository (RED until Task 3 creates repositories).
"""
import pytest
import pytest_asyncio

from src.sms.exceptions import DuplicateMessageSid, RateLimitExceeded
from src.sms.constants import MAX_MESSAGES_PER_WINDOW


@pytest.mark.asyncio
async def test_check_idempotency_existing(async_session, make_message):
    """check_idempotency raises DuplicateMessageSid if message_sid already exists."""
    from src.sms.repository import MessageRepository

    message = await make_message()
    with pytest.raises(DuplicateMessageSid):
        await MessageRepository.check_idempotency(async_session, message.message_sid)


@pytest.mark.asyncio
async def test_check_idempotency_new(async_session):
    """check_idempotency returns None for unknown message_sid (no raise)."""
    from src.sms.repository import MessageRepository

    result = await MessageRepository.check_idempotency(async_session, "unknown-sid-xyz")
    assert result is None


@pytest.mark.asyncio
async def test_enforce_rate_limit_under_limit(async_session, make_user):
    """enforce_rate_limit does not raise when under the window limit."""
    from src.sms.repository import MessageRepository

    user = await make_user()
    # Should not raise
    await MessageRepository.enforce_rate_limit(async_session, user.id)


@pytest.mark.asyncio
async def test_enforce_rate_limit_over_limit(async_session, make_user):
    """enforce_rate_limit raises RateLimitExceeded after MAX_MESSAGES_PER_WINDOW calls."""
    from src.sms.repository import MessageRepository

    user = await make_user()
    with pytest.raises(RateLimitExceeded):
        for _ in range(MAX_MESSAGES_PER_WINDOW + 1):
            await MessageRepository.enforce_rate_limit(async_session, user.id)


@pytest.mark.asyncio
async def test_audit_log_write(async_session, make_message):
    """AuditLogRepository.write inserts a row that exists after caller commits."""
    from src.sms.audit_repository import AuditLogRepository
    from src.sms.models import AuditLog
    from sqlmodel import select

    message = await make_message()
    await AuditLogRepository.write(
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
