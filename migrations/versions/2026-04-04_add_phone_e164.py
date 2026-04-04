"""add phone_e164 to user

Revision ID: 004
Revises: 003
Create Date: 2026-04-04
"""

from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: str = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user", sa.Column("phone_e164", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("user", "phone_e164")
