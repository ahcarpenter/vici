class TwilioSignatureInvalid(Exception):
    pass


class EarlyReturn(Exception):
    """Raised by dependencies to short-circuit processing with HTTP 200 TwiML response.
    The exception handler in src/sms/error_handlers.py converts this to HTTP 200.
    Never raise HTTPException for Twilio webhook paths — Twilio retries on 4xx
    responses."""

    def __init__(self, reason: str = ""):
        self.reason = reason
        super().__init__(reason)


class DuplicateMessageSid(EarlyReturn):
    pass


class RateLimitExceeded(EarlyReturn):
    pass
