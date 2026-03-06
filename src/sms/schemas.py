from pydantic import BaseModel, ConfigDict


class TwilioWebhookPayload(BaseModel):
    MessageSid: str
    From: str  # E.164 phone number
    Body: str
    AccountSid: str
    model_config = ConfigDict(extra="allow")  # Twilio sends many extra fields
