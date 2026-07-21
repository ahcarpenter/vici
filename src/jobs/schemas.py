from datetime import UTC, datetime

import structlog
from pydantic import BaseModel, Field, field_validator

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
        if value is None or isinstance(value, datetime):
            parsed = value
        else:
            try:
                parsed = datetime.fromisoformat(str(value))
            except (ValueError, TypeError):
                structlog.get_logger().warning(
                    "job.ideal_datetime_parse_failed", raw_value=str(value)
                )
                return None
        if parsed is not None and parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed
