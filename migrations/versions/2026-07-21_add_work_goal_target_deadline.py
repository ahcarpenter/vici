"""add work_goal.target_deadline — timeframe-aware matching

Revision ID: 008
Revises: 007
Create Date: 2026-07-21
"""

from alembic import op
import sqlalchemy as sa

revision: str = "008"
down_revision: str = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "work_goal",
        sa.Column("target_deadline", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("work_goal", "target_deadline")
