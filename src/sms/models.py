from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class Phone(SQLModel, table=True):
    __tablename__ = "phone"
    id: Optional[int] = Field(default=None, primary_key=True)
    phone_hash: str = Field(unique=True, index=True)  # SHA-256 of E.164 number (IDN-01)
    created_at: datetime = Field(default_factory=datetime.utcnow)  # IDN-02: recycling detection


class InboundMessage(SQLModel, table=True):
    __tablename__ = "inbound_message"
    id: Optional[int] = Field(default=None, primary_key=True)
    message_sid: str = Field(unique=True, index=True)  # Twilio MessageSid; idempotency key (SEC-02)
    phone_hash: str = Field(index=True)                 # FK-like ref to phone.phone_hash
    body: str
    raw_sms: str                                         # Full raw form payload as JSON string (SEC-04)
    raw_gpt_response: Optional[str] = None               # Populated in Phase 2 (SEC-04)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RateLimit(SQLModel, table=True):
    __tablename__ = "rate_limit"
    __table_args__ = (
        UniqueConstraint("phone_hash", "window_start", name="uq_rate_limit_phone_window"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    phone_hash: str = Field(index=True)                  # SHA-256 of phone number
    window_start: datetime                               # Truncated to 1-minute bucket
    count: int = Field(default=1)


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"
    id: Optional[int] = Field(default=None, primary_key=True)
    message_sid: str = Field(index=True)
    event: str                                           # e.g. "received", "rate_limited", "duplicate"
    detail: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
