from pydantic import BaseModel, ConfigDict, Field


class TwilioWebhookPayload(BaseModel):
    MessageSid: str = Field(min_length=1, max_length=64)
    From: str = Field(min_length=1, max_length=20)  # E.164: +[1-15 digits]
    Body: str = Field(min_length=0, max_length=1600)  # SMS can be empty
    AccountSid: str = Field(min_length=1, max_length=64)
    model_config = ConfigDict(extra="allow")  # Twilio sends many extra fields
