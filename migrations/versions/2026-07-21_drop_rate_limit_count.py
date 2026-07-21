"""drop vestigial rate_limit.count — rolling-window inserts one row per event

Revision ID: 007
Revises: 006
Create Date: 2026-07-21
"""

from alembic import op
import sqlalchemy as sa

revision: str = "007"
down_revision: str = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("rate_limit", "count")


def downgrade() -> None:
    op.add_column(
        "rate_limit",
        sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
    )
