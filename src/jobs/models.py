from datetime import UTC, datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import CheckConstraint
from sqlmodel import Field, SQLModel


class Job(SQLModel, table=True):
    __tablename__ = "job"
    __table_args__ = (
        CheckConstraint("pay_rate > 0", name="ck_job_pay_rate_positive"),
        CheckConstraint(
            "estimated_duration_hours IS NULL OR estimated_duration_hours > 0",
            name="ck_job_estimated_duration_positive",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=sa.Column(
            sa.Integer, sa.ForeignKey("user.id", ondelete="RESTRICT"), nullable=False
        )
    )
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
    pay_rate: float
    estimated_duration_hours: Optional[float] = None
    ideal_datetime: Optional[datetime] = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True),
    )
    datetime_flexible: Optional[bool] = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )
