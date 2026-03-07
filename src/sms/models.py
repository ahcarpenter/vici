from datetime import UTC, datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class Message(SQLModel, table=True):
    __tablename__ = "message"

    id: Optional[int] = Field(default=None, primary_key=True)
    message_sid: str = Field(unique=True, index=True)
    user_id: int = Field(
        sa_column=sa.Column(
            sa.Integer, sa.ForeignKey("user.id", ondelete="RESTRICT"), nullable=False
        )
    )
    body: str
    message_type: Optional[str] = None
    raw_gpt_response: Optional[str] = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )


class RateLimit(SQLModel, table=True):
    __tablename__ = "rate_limit"
    __table_args__ = (
        UniqueConstraint("user_id", "window_start", name="uq_rate_limit_user_window"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=sa.Column(
            sa.Integer, sa.ForeignKey("user.id", ondelete="RESTRICT"), nullable=False
        )
    )
    window_start: datetime = Field(
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False)
    )
    count: int = Field(default=1)


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: Optional[int] = Field(default=None, primary_key=True)
    message_sid: str = Field(index=True)
    message_id: Optional[int] = Field(
        default=None,
        sa_column=sa.Column(
            sa.Integer, sa.ForeignKey("message.id", ondelete="SET NULL"), nullable=True
        ),
    )
    event: str
    detail: Optional[str] = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )
