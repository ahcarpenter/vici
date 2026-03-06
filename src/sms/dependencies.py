from fastapi import HTTPException, Request, status
from twilio.request_validator import RequestValidator
from src.config import settings


async def validate_twilio_request(request: Request) -> dict:
    validator = RequestValidator(settings.twilio_auth_token)
    form_data = dict(await request.form())
    # Reconstruct the public URL Twilio actually signed
    url = f"{settings.webhook_base_url}{request.url.path}"
    signature = request.headers.get("X-Twilio-Signature", "")
    if not validator.validate(url, form_data, signature):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Twilio signature",
        )
    return form_data
