import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from opentelemetry import trace as otel_trace
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.observability import (
    OTEL_ATTR_MESSAGE_ID,
    OTEL_ATTR_MESSAGING_SYSTEM,
    OTEL_ATTR_PHONE_HASH,
)
from src.sms.audit_repository import AuditLogRepository
from src.sms.constants import EMPTY_TWIML, AuditEvent
from src.sms.dependencies import enforce_rate_limit, get_audit_repo, get_message_repo
from src.sms.repository import MessageRepository
from src.sms.schemas import InboundSms
from src.sms.service import hash_phone, scrub_phone_fields
from src.temporal.worker import start_process_message_workflow

router = APIRouter(prefix="/webhook", tags=["sms"])


@router.post("/sms")
async def receive_sms(
    request: Request,
    inbound: InboundSms = Depends(enforce_rate_limit),
    session: AsyncSession = Depends(get_session),
    message_repo: MessageRepository = Depends(get_message_repo),
    audit_repo: AuditLogRepository = Depends(get_audit_repo),
):
    """Receive inbound SMS from Twilio.

    All pre-flight gates (signature validation, idempotency, user upsert,
    rate limiting) handled by Depends() chain. Route body only persists
    and emits (per D-07).
    """
    payload = inbound.payload
    assert inbound.sender.id is not None  # upserted by the gate chain

    span = otel_trace.get_current_span()
    span.set_attribute(OTEL_ATTR_MESSAGE_ID, payload.MessageSid)
    span.set_attribute(OTEL_ATTR_PHONE_HASH, hash_phone(payload.From))
    span.set_attribute(OTEL_ATTR_MESSAGING_SYSTEM, "twilio")

    async with session.begin():
        message = await message_repo.create(
            session, payload.MessageSid, inbound.sender.id, payload.Body
        )
        await audit_repo.write(
            session,
            payload.MessageSid,
            AuditEvent.RECEIVED,
            detail=json.dumps(scrub_phone_fields(payload.model_dump())),
            message_id=message.id,
        )

    await start_process_message_workflow(
        request.app.state.temporal_client,
        message_sid=payload.MessageSid,
        from_number=payload.From,
        body=payload.Body,
    )

    return Response(content=EMPTY_TWIML, media_type="text/xml")
