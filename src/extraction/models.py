from datetime import UTC, datetime
from typing import Optional

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


class PineconeSyncQueue(SQLModel, table=True):
    __tablename__ = "pinecone_sync_queue"

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(
        sa_column=sa.Column(
            sa.Integer, sa.ForeignKey("job.id", ondelete="CASCADE"), nullable=False
        )
    )
    status: str = Field(default="pending")
    attempts: int = Field(default=0)
    last_error: Optional[str] = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )
