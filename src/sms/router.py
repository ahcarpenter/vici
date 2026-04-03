import json

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.sms import service as sms_service
from src.sms.audit_repository import AuditLogRepository
from src.sms.dependencies import enforce_rate_limit
from src.sms.exceptions import EMPTY_TWIML
from src.sms.repository import MessageRepository

router = APIRouter(prefix="/webhook", tags=["sms"])


@router.post("/sms")
async def receive_sms(
    gates=Depends(enforce_rate_limit),
    session: AsyncSession = Depends(get_session),
):
    """Receive inbound SMS from Twilio.

    All pre-flight gates (signature validation, idempotency, user upsert,
    rate limiting) handled by Depends() chain. Route body only persists
    and emits (per D-07).
    """
    form_data, user = gates
    message_sid = form_data.get("MessageSid", "")
    from_number = form_data.get("From", "")
    body = form_data.get("Body", "")

    async with session.begin():
        message = await MessageRepository().create(session, message_sid, user.id, body)
        await AuditLogRepository().write(
            session,
            message_sid,
            "received",
            detail=json.dumps(dict(form_data)),
            message_id=message.id,
        )

    await sms_service.emit_message_received_event(
        request.app.state.temporal_client, message_sid, from_number, body
    )

    return Response(content=EMPTY_TWIML, media_type="text/xml")
