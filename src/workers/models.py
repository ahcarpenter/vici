from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Worker(SQLModel, table=True):
    __tablename__ = "worker"
    id: Optional[int] = Field(default=None, primary_key=True)
    phone_hash: str = Field(index=True)
    target_earnings: Optional[float] = None
    target_timeframe: Optional[str] = None
    raw_sms: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
