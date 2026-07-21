from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from src.datetimes import coerce_llm_datetime
from src.jobs.constants import PayType


class JobCreate(BaseModel):
    message_id: int = Field(gt=0)
    description: str = Field(min_length=1, max_length=1000)
    location: str = Field(min_length=1, max_length=255)
    pay_rate: int | None = Field(default=None, gt=0)
    pay_type: PayType = PayType.UNKNOWN
    estimated_duration_hours: float | None = Field(default=None, gt=0)
    raw_duration_text: str | None = Field(default=None, max_length=255)
    ideal_datetime: datetime | None = None
    raw_datetime_text: str | None = Field(default=None, max_length=255)
    inferred_timezone: str | None = Field(default=None, max_length=100)
    datetime_flexible: bool = False

    @field_validator("ideal_datetime", mode="before")
    @classmethod
    def _coerce_ideal_datetime(cls, value: object) -> datetime | None:
        """Null out unparseable LLM datetimes instead of failing the message.

        The GPT contract asks for ISO-8601 but cannot guarantee it; a junk
        value must degrade to "no datetime" (raw_datetime_text is preserved),
        not poison the whole pipeline run.
        """
        return coerce_llm_datetime(value, log_event="job.ideal_datetime_parse_failed")
