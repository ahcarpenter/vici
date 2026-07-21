from datetime import UTC, datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    __tablename__ = "user"

    id: int | None = Field(default=None, primary_key=True)
    phone_hash: str = Field(unique=True, index=True)
    phone_e164: str | None = Field(
        default=None,
        sa_column=sa.Column(sa.String(), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )
