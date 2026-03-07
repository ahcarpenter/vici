from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class JobCreate(BaseModel):
    user_id: int
    message_id: int
    description: str
    location: str
    pay_rate: Optional[float] = None
    pay_type: str = "unknown"
    estimated_duration_hours: Optional[float] = None
    raw_duration_text: Optional[str] = None
    ideal_datetime: Optional[datetime] = None
    raw_datetime_text: Optional[str] = None
    inferred_timezone: Optional[str] = None
    datetime_flexible: bool = False
    raw_sms: str
