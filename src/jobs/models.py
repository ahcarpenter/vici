from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Job(SQLModel, table=True):
    __tablename__ = "job"
    id: Optional[int] = Field(default=None, primary_key=True)
    phone_hash: str = Field(index=True)
    description: Optional[str] = None
    location: Optional[str] = None
    pay_rate: Optional[float] = None
    estimated_duration_hours: Optional[float] = None
    ideal_datetime: Optional[datetime] = None
    datetime_flexible: Optional[bool] = None
    raw_sms: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
