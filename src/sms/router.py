import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.inngest_client import get_inngest_client
from src.sms import service as sms_service
from src.sms.dependencies import validate_twilio_request

router = APIRouter(prefix="/webhook", tags=["sms"])

EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response/>'


@router.post("/sms")
async def receive_sms(
    request: Request,
    form_data: dict = Depends(validate_twilio_request),
    session: AsyncSession = Depends(get_session),
):
    message_sid = form_data.get("MessageSid", "")
    from_number = form_data.get("From", "")
    body = form_data.get("Body", "")

    phone_hash = sms_service.hash_phone(from_number)

    async with session.begin():
        # Gate 2: idempotency (cheapest DB read — fires before user registration)
        is_duplicate = await sms_service.check_idempotency(session, message_sid)
        if is_duplicate:
            await sms_service.write_audit_log(session, message_sid, "duplicate")
            return Response(content=EMPTY_TWIML, media_type="text/xml")

        # Gate 3: get/create user (required before rate limit — rate limit needs user_id)
        user = await sms_service.get_or_create_user(session, phone_hash)

        # Gate 4: rate limit check
        is_rate_limited = await sms_service.enforce_rate_limit(session, user.id)
        if is_rate_limited:
            await sms_service.write_audit_log(session, message_sid, "rate_limited")
            return Response(content=EMPTY_TWIML, media_type="text/xml")

        # Gate 5: persist message + audit
        message = await sms_service.write_inbound_message(session, message_sid, user.id, body)
        await sms_service.write_audit_log(
            session, message_sid, "received",
            detail=json.dumps(dict(form_data)), message_id=message.id
        )

    # Emit after DB commit
    await sms_service.emit_message_received_event(
        get_inngest_client(), message_sid, from_number, body
    )

    return Response(content=EMPTY_TWIML, media_type="text/xml")
