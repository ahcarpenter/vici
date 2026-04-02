from urllib.parse import urlsplit, urlunsplit

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from twilio.request_validator import RequestValidator

from src.config import get_settings
from src.database import get_session
from src.sms import service as sms_service
from src.sms.audit_repository import AuditLogRepository
from src.sms.exceptions import (
    DuplicateMessageSid,
    RateLimitExceeded,
    TwilioSignatureInvalid,
)
from src.sms.repository import MessageRepository
from src.users.repository import UserRepository


def _canonical_base_url(raw_base: str) -> str:
    # Ensure no trailing slash and preserve scheme/host/port.
    base = raw_base.rstrip("/")
    parts = urlsplit(base)
    # If someone passes "example.com" by accident, make it explicit rather than
    # silently constructing an invalid URL for signature validation.
    if not parts.scheme or not parts.netloc:
        raise ValueError(
            "WEBHOOK_BASE_URL must include scheme and host, e.g. https://example.com"
        )
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _public_request_url(request: Request) -> str:
    """
    Return the exact public URL Twilio signed.

    We prefer a configured WEBHOOK_BASE_URL (canonical external URL) because
    proxy headers can vary across environments.
    """
    settings = get_settings()
    base = _canonical_base_url(settings.webhook_base_url)
    path = request.url.path
    query = request.url.query
    return f"{base}{path}" + (f"?{query}" if query else "")


async def validate_twilio_request(request: Request) -> dict:
    settings = get_settings()
    form_data = dict(await request.form())
    if settings.env == "development":
        return form_data
    validator = RequestValidator(settings.sms.auth_token)
    url = _public_request_url(request)
    signature = request.headers.get("X-Twilio-Signature", "")
    if not validator.validate(url, form_data, signature):
        raise TwilioSignatureInvalid()
    return form_data


async def check_idempotency(
    form_data: dict = Depends(validate_twilio_request),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Gate 2: Raise DuplicateMessageSid (-> HTTP 200 via handler) if MessageSid seen.
    Returns form_data for downstream deps to chain."""
    message_sid = form_data.get("MessageSid", "")
    try:
        async with session.begin():
            await MessageRepository.check_idempotency(session, message_sid)
    except DuplicateMessageSid:
        async with session.begin():
            await AuditLogRepository.write(session, message_sid, "duplicate")
        raise
    return form_data


async def get_or_create_user(
    form_data: dict = Depends(check_idempotency),
    session: AsyncSession = Depends(get_session),
):
    """Gate 3: Upsert user by phone_hash. Returns (form_data, user) tuple."""
    from_number = form_data.get("From", "")
    phone_hash = sms_service.hash_phone(from_number)
    async with session.begin():
        user = await UserRepository.get_or_create(session, phone_hash)
    return form_data, user


async def enforce_rate_limit(
    form_and_user=Depends(get_or_create_user),
    session: AsyncSession = Depends(get_session),
):
    """Gate 4: Raise RateLimitExceeded (-> HTTP 200 via handler) if over limit.
    Returns (form_data, user) for route to consume."""
    form_data, user = form_and_user
    message_sid = form_data.get("MessageSid", "")
    try:
        async with session.begin():
            await MessageRepository.enforce_rate_limit(session, user.id)
    except RateLimitExceeded:
        async with session.begin():
            await AuditLogRepository.write(session, message_sid, "rate_limited")
        raise
    return form_data, user
