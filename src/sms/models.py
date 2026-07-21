from datetime import UTC, datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


class Message(SQLModel, table=True):
    __tablename__ = "message"

    id: int | None = Field(default=None, primary_key=True)
    message_sid: str = Field(unique=True, index=True)
    user_id: int = Field(
        sa_column=sa.Column(
            sa.Integer, sa.ForeignKey("user.id", ondelete="RESTRICT"), nullable=False
        )
    )
    body: str
    message_type: str | None = None
    raw_gpt_response: str | None = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )


class RateLimit(SQLModel, table=True):
    """One row per admitted message — counted over a rolling window."""

    __tablename__ = "rate_limit"
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=sa.Column(
            sa.Integer, sa.ForeignKey("user.id", ondelete="RESTRICT"), nullable=False
        )
    )
    created_at: datetime = Field(
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False)
    )


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: int | None = Field(default=None, primary_key=True)
    message_sid: str = Field(index=True)
    message_id: int | None = Field(
        default=None,
        sa_column=sa.Column(
            sa.Integer, sa.ForeignKey("message.id", ondelete="SET NULL"), nullable=True
        ),
    )
    event: str
    detail: str | None = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )
