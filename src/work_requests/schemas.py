from pydantic import BaseModel


class WorkRequestCreate(BaseModel):
    user_id: int
    message_id: int
    target_earnings: float
    target_timeframe: str
    raw_sms: str
