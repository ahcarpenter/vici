from pydantic import BaseModel, Field


class WorkGoalCreate(BaseModel):
    message_id: int = Field(gt=0)
    target_earnings: float = Field(gt=0)
    target_timeframe: str = Field(min_length=1, max_length=255)
    raw_sms: str = Field(min_length=1, max_length=1600)
