from datetime import UTC, datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import CheckConstraint
from sqlmodel import Field, SQLModel


class WorkRequest(SQLModel, table=True):
    __tablename__ = "work_request"
    __table_args__ = (
        CheckConstraint(
            "target_earnings > 0", name="ck_work_request_target_earnings_positive"
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
    target_earnings: float = Field(gt=0)
    target_timeframe: Optional[str] = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )
