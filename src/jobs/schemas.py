from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class JobCreate(BaseModel):
    message_id: int = Field(gt=0)
    description: str = Field(min_length=1, max_length=1000)
    location: str = Field(min_length=1, max_length=255)
    pay_rate: Optional[int] = Field(default=None, gt=0)
    pay_type: str = Field(default="unknown", min_length=1, max_length=50)
    estimated_duration_hours: Optional[float] = Field(default=None, gt=0)
    raw_duration_text: Optional[str] = Field(default=None, max_length=255)
    ideal_datetime: Optional[datetime] = None
    raw_datetime_text: Optional[str] = Field(default=None, max_length=255)
    inferred_timezone: Optional[str] = Field(default=None, max_length=100)
    datetime_flexible: bool = False
    raw_sms: str = Field(min_length=1, max_length=1600)
