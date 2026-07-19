import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from opentelemetry import trace as otel_trace
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.pipeline.constants import (
    OTEL_ATTR_MESSAGE_ID,
    OTEL_ATTR_MESSAGING_SYSTEM,
    OTEL_ATTR_PHONE_HASH,
)
from src.sms import service as sms_service
from src.sms.audit_repository import AuditLogRepository
from src.sms.constants import AuditEvent
from src.sms.dependencies import enforce_rate_limit
from src.sms.exceptions import EMPTY_TWIML
from src.sms.repository import MessageRepository
from src.sms.schemas import InboundSms
from src.sms.service import hash_phone, scrub_phone_fields

router = APIRouter(prefix="/webhook", tags=["sms"])


@router.post("/sms")
async def receive_sms(
    request: Request,
    inbound: InboundSms = Depends(enforce_rate_limit),
    session: AsyncSession = Depends(get_session),
):
    """Receive inbound SMS from Twilio.

    All pre-flight gates (signature validation, idempotency, user upsert,
    rate limiting) handled by Depends() chain. Route body only persists
    and emits (per D-07).
    """
    payload = inbound.payload

    span = otel_trace.get_current_span()
    span.set_attribute(OTEL_ATTR_MESSAGE_ID, payload.MessageSid)
    span.set_attribute(OTEL_ATTR_PHONE_HASH, hash_phone(payload.From))
    span.set_attribute(OTEL_ATTR_MESSAGING_SYSTEM, "twilio")

    async with session.begin():
        message = await MessageRepository().create(
            session, payload.MessageSid, inbound.sender.id, payload.Body
        )
        await AuditLogRepository().write(
            session,
            payload.MessageSid,
            AuditEvent.RECEIVED,
            detail=json.dumps(scrub_phone_fields(payload.model_dump())),
            message_id=message.id,
        )

    await sms_service.emit_message_received_event(
        request.app.state.temporal_client,
        payload.MessageSid,
        payload.From,
        payload.Body,
    )

    return Response(content=EMPTY_TWIML, media_type="text/xml")
