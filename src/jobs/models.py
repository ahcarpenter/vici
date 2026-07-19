from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import CheckConstraint
from sqlmodel import Field, SQLModel

from src.jobs.constants import (
    INCOMPUTABLE_NULL_DURATION_HOURLY,
    INCOMPUTABLE_NULL_PAY_RATE,
    INCOMPUTABLE_UNKNOWN_PAY_TYPE,
    JobStatus,
    PayType,
)


@dataclass(frozen=True)
class PayTerms:
    """Value object: how a job pays and whether its earnings are computable.

    Earnings are integer cents. Hourly jobs need a duration to be computable;
    flat jobs pay their rate outright.
    """

    rate: Optional[int]  # integer cents
    pay_type: PayType
    duration_hours: Optional[float]

    def earnings(self) -> Optional[int]:
        """Total earnings in cents, or None when they cannot be computed."""
        if self.incomputable_reason() is not None:
            return None
        if self.pay_type is PayType.HOURLY:
            return int(round(self.rate * self.duration_hours))
        return self.rate

    def incomputable_reason(self) -> Optional[str]:
        """Why earnings cannot be computed, or None when they can."""
        if self.pay_type is PayType.UNKNOWN:
            return INCOMPUTABLE_UNKNOWN_PAY_TYPE
        if self.rate is None:
            return INCOMPUTABLE_NULL_PAY_RATE
        if self.pay_type is PayType.HOURLY and self.duration_hours is None:
            return INCOMPUTABLE_NULL_DURATION_HOURLY
        return None


class Job(SQLModel, table=True):
    __tablename__ = "job"
    __table_args__ = (
        CheckConstraint("pay_rate > 0", name="ck_job_pay_rate_positive"),
        CheckConstraint(
            "estimated_duration_hours IS NULL OR estimated_duration_hours > 0",
            name="ck_job_estimated_duration_positive",
        ),
        CheckConstraint(
            "status IN ('available', 'accepted', 'in_progress', 'completed')",
            name="ck_job_status_valid",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    message_id: int = Field(
        sa_column=sa.Column(
            sa.Integer,
            sa.ForeignKey("message.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        )
    )
    description: Optional[str] = None
    location: Optional[str] = None
    pay_rate: Optional[int] = Field(
        default=None,
        sa_column=sa.Column(sa.Integer, nullable=True),
    )
    pay_type: str = Field(default=PayType.UNKNOWN)
    estimated_duration_hours: Optional[float] = None
    raw_duration_text: Optional[str] = None
    ideal_datetime: Optional[datetime] = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True),
    )
    raw_datetime_text: Optional[str] = None
    inferred_timezone: Optional[str] = None
    datetime_flexible: Optional[bool] = None
    status: str = Field(
        default=JobStatus.AVAILABLE,
        sa_column=sa.Column(sa.String(), nullable=False, server_default="available"),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )

    @property
    def pay_terms(self) -> PayTerms:
        return PayTerms(
            rate=self.pay_rate,
            pay_type=PayType(self.pay_type),
            duration_hours=self.estimated_duration_hours,
        )
