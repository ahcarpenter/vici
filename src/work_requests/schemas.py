from pydantic import BaseModel


class WorkRequestCreate(BaseModel):
    message_id: int
    target_earnings: float
    target_timeframe: str
    raw_sms: str
