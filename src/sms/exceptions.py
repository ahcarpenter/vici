from fastapi import Request
from fastapi.responses import Response

EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response/>'


class TwilioSignatureInvalid(Exception):
    pass


class EarlyReturn(Exception):
    """Raised by dependencies to short-circuit processing with HTTP 200 TwiML response.
    FastAPI exception handler converts this to HTTP 200. Never raise HTTPException
    for Twilio webhook paths — Twilio retries on 4xx responses."""

    def __init__(self, reason: str = ""):
        self.reason = reason
        super().__init__(reason)


class DuplicateMessageSid(EarlyReturn):
    pass


class RateLimitExceeded(EarlyReturn):
    pass


async def early_return_handler(request: Request, exc: EarlyReturn) -> Response:
    """Return HTTP 200 with empty TwiML for any EarlyReturn subclass.
    Audit logging happens in the dependency that raises, not here (per D-06)."""
    return Response(content=EMPTY_TWIML, media_type="text/xml")
