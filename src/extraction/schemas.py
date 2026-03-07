from typing import Literal, Optional

from pydantic import BaseModel


class JobExtraction(BaseModel):
    description: str
    ideal_datetime: Optional[str] = None
    raw_datetime_text: Optional[str] = None
    inferred_timezone: Optional[str] = None
    datetime_flexible: bool
    estimated_duration_hours: Optional[float] = None
    raw_duration_text: Optional[str] = None
    location: str
    pay_rate: Optional[float] = None
    pay_type: Literal["hourly", "flat", "unknown"]


class WorkerExtraction(BaseModel):
    target_earnings: float
    target_timeframe: str


class UnknownMessage(BaseModel):
    reason: str


class ExtractionResult(BaseModel):
    message_type: Literal["job_posting", "worker_goal", "unknown"]
    job: Optional[JobExtraction] = None
    worker: Optional[WorkerExtraction] = None
    unknown: Optional[UnknownMessage] = None
