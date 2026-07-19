from urllib.parse import urlsplit, urlunsplit

from fastapi import Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from twilio.request_validator import RequestValidator

from src.config import get_settings
from src.database import get_session
from src.sms import service as sms_service
from src.sms.audit_repository import AuditLogRepository
from src.sms.constants import AuditEvent
from src.sms.exceptions import (
    DuplicateMessageSid,
    RateLimitExceeded,
    TwilioSignatureInvalid,
)
from src.sms.repository import MessageRepository
from src.sms.schemas import InboundSms, TwilioWebhookPayload
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


async def validate_twilio_request(request: Request) -> TwilioWebhookPayload:
    """Gate 1: Parse the payload (400 on contract violation) and verify the
    Twilio signature against the raw form (403 via handler on mismatch)."""
    settings = get_settings()
    form_data = dict(await request.form())
    try:
        payload = TwilioWebhookPayload(**form_data)
    except ValidationError as exc:
        missing = ", ".join(str(err["loc"][0]) for err in exc.errors())
        raise HTTPException(
            status_code=400,
            detail=f"Invalid Twilio payload: {missing}",
        ) from exc
    if settings.sms.disable_twilio_signature_validation:
        return payload
    validator = RequestValidator(settings.sms.auth_token)
    url = _public_request_url(request)
    signature = request.headers.get("X-Twilio-Signature", "")
    if not validator.validate(url, form_data, signature):
        raise TwilioSignatureInvalid()
    return payload


async def check_idempotency(
    payload: TwilioWebhookPayload = Depends(validate_twilio_request),
    session: AsyncSession = Depends(get_session),
) -> TwilioWebhookPayload:
    """Gate 2: Raise DuplicateMessageSid (-> HTTP 200 via handler) if MessageSid seen.
    Returns the payload for downstream deps to chain."""
    try:
        async with session.begin():
            await MessageRepository.check_idempotency(session, payload.MessageSid)
    except DuplicateMessageSid:
        async with session.begin():
            await AuditLogRepository().write(
                session, payload.MessageSid, AuditEvent.DUPLICATE
            )
        raise
    return payload


async def get_or_create_user(
    payload: TwilioWebhookPayload = Depends(check_idempotency),
    session: AsyncSession = Depends(get_session),
) -> InboundSms:
    """Gate 3: Upsert user by phone_hash. Returns the admitted InboundSms."""
    phone_hash = sms_service.hash_phone(payload.From)
    async with session.begin():
        user = await UserRepository.get_or_create(session, phone_hash)
    return InboundSms(payload=payload, sender=user)


async def enforce_rate_limit(
    inbound: InboundSms = Depends(get_or_create_user),
    session: AsyncSession = Depends(get_session),
) -> InboundSms:
    """Gate 4: Raise RateLimitExceeded (-> HTTP 200 via handler) if over limit.
    Returns the admitted InboundSms for the route to consume."""
    try:
        async with session.begin():
            await MessageRepository.enforce_rate_limit(session, inbound.sender.id)
    except RateLimitExceeded:
        async with session.begin():
            await AuditLogRepository().write(
                session, inbound.payload.MessageSid, AuditEvent.RATE_LIMITED
            )
        raise
    return inbound
