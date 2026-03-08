from urllib.parse import urlsplit, urlunsplit

from fastapi import Request
from twilio.request_validator import RequestValidator

from src.config import get_settings
from src.sms.exceptions import TwilioSignatureInvalid


def _canonical_base_url(raw_base: str) -> str:
    # Ensure no trailing slash and preserve scheme/host/port.
    base = raw_base.rstrip("/")
    parts = urlsplit(base)
    # If someone passes "example.com" by accident, make it explicit rather than
    # silently constructing an invalid URL for signature validation.
    if not parts.scheme or not parts.netloc:
        raise ValueError("WEBHOOK_BASE_URL must include scheme and host, e.g. https://example.com")
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
