"""FastAPI exception handlers for the SMS webhook path.

Kept apart from src/sms/exceptions.py so the exception types stay free of
framework imports.
"""

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from src.sms.constants import EMPTY_TWIML
from src.sms.exceptions import EarlyReturn, TwilioSignatureInvalid


async def early_return_handler(request: Request, exc: EarlyReturn) -> Response:
    """Return HTTP 200 with empty TwiML for any EarlyReturn subclass.
    Audit logging happens in the dependency that raises, not here (per D-06)."""
    return Response(content=EMPTY_TWIML, media_type="text/xml")


async def twilio_signature_invalid_handler(
    request: Request,
    exc: TwilioSignatureInvalid,
) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"detail": "Invalid Twilio signature"},
    )
