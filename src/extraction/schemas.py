from typing import Literal, Optional

from pydantic import BaseModel, Field


class JobExtraction(BaseModel):
    description: str = Field(min_length=1, max_length=1000)
    ideal_datetime: Optional[str] = Field(default=None, max_length=100)
    raw_datetime_text: Optional[str] = Field(default=None, max_length=255)
    inferred_timezone: Optional[str] = Field(default=None, max_length=100)
    datetime_flexible: bool
    estimated_duration_hours: Optional[float] = Field(default=None, gt=0)
    raw_duration_text: Optional[str] = Field(default=None, max_length=255)
    location: str = Field(min_length=1, max_length=255)
    pay_rate: Optional[float] = Field(default=None, gt=0)
    pay_type: Literal["hourly", "flat", "unknown"]


class WorkerExtraction(BaseModel):
    target_earnings: float = Field(gt=0)
    target_timeframe: str = Field(min_length=1, max_length=255)


class UnknownMessage(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class ExtractionResult(BaseModel):
    message_type: Literal["job_posting", "work_goal", "unknown"]
    job: Optional[JobExtraction] = None
    work_goal: Optional[WorkerExtraction] = None
    unknown: Optional[UnknownMessage] = None
