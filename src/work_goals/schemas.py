from pydantic import BaseModel, Field


class WorkGoalCreate(BaseModel):
    message_id: int = Field(gt=0)
    target_earnings: int = Field(gt=0)
    target_timeframe: str = Field(min_length=1, max_length=255)
