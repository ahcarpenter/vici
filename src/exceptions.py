from fastapi import Request
from fastapi.responses import JSONResponse

from src.sms.exceptions import TwilioSignatureInvalid


async def twilio_signature_invalid_handler(
    request: Request,
    exc: TwilioSignatureInvalid,
):
    return JSONResponse(
        status_code=403,
        content={"detail": "Invalid Twilio signature"},
    )
