from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from src.datetimes import coerce_llm_datetime


class WorkGoalCreate(BaseModel):
    message_id: int = Field(gt=0)
    target_earnings: int = Field(gt=0)
    target_timeframe: str = Field(min_length=1, max_length=255)
    target_deadline: datetime | None = None

    @field_validator("target_deadline", mode="before")
    @classmethod
    def _coerce_target_deadline(cls, value: object) -> datetime | None:
        """Null out unparseable LLM deadlines instead of failing the message.

        target_timeframe preserves the raw phrase; a junk deadline degrades to
        "no deadline" (matching behaves as before), not a pipeline failure.
        """
        return coerce_llm_datetime(
            value, log_event="work_goal.target_deadline_parse_failed"
        )
