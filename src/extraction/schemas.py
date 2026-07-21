from typing import Literal

from pydantic import BaseModel, Field

from src.extraction.constants import MessageType


class JobExtraction(BaseModel):
    description: str = Field(min_length=1, max_length=1000)
    ideal_datetime: str | None = Field(default=None, max_length=100)
    raw_datetime_text: str | None = Field(default=None, max_length=255)
    inferred_timezone: str | None = Field(default=None, max_length=100)
    datetime_flexible: bool
    estimated_duration_hours: float | None = Field(default=None, gt=0)
    raw_duration_text: str | None = Field(default=None, max_length=255)
    location: str = Field(min_length=1, max_length=255)
    pay_rate: float | None = Field(default=None, gt=0)
    pay_type: Literal["hourly", "flat", "unknown"]


class WorkGoalExtraction(BaseModel):
    target_earnings: float = Field(gt=0)
    target_timeframe: str = Field(min_length=1, max_length=255)
    target_deadline: str | None = Field(default=None, max_length=100)


class UnknownMessage(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class ExtractionResult(BaseModel):
    message_type: MessageType
    job: JobExtraction | None = None
    work_goal: WorkGoalExtraction | None = None
    unknown: UnknownMessage | None = None
