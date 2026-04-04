"""add status to job

Revision ID: 005
Revises: 004
Create Date: 2026-04-04
"""

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: str = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "job",
        sa.Column("status", sa.String(), nullable=False, server_default="available"),
    )
    op.create_check_constraint(
        "ck_job_status_valid",
        "job",
        "status IN ('available', 'accepted', 'in_progress', 'completed')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_job_status_valid", "job", type_="check")
    op.drop_column("job", "status")
