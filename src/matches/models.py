from datetime import UTC, datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class Match(SQLModel, table=True):
    __tablename__ = "match"
    __table_args__ = (
        UniqueConstraint("job_id", "work_request_id", name="uq_match_job_work_request"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(
        sa_column=sa.Column(
            sa.Integer, sa.ForeignKey("job.id", ondelete="RESTRICT"), nullable=False
        )
    )
    work_request_id: int = Field(
        sa_column=sa.Column(
            sa.Integer,
            sa.ForeignKey("work_request.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )
