"""extraction_additions

Revision ID: 002
Revises: 001
Create Date: 2026-03-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, Sequence[str], None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new columns to job table
    op.add_column(
        "job",
        sa.Column(
            "pay_type",
            sqlmodel.AutoString(),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.create_check_constraint(
        "ck_job_pay_type", "job", "pay_type IN ('hourly', 'flat', 'unknown')"
    )
    op.add_column("job", sa.Column("raw_datetime_text", sa.Text(), nullable=True))
    op.add_column("job", sa.Column("inferred_timezone", sa.Text(), nullable=True))
    op.add_column("job", sa.Column("raw_duration_text", sa.Text(), nullable=True))

    # Make pay_rate nullable (optional in GPT extraction schema)
    op.alter_column("job", "pay_rate", existing_type=sa.Float(), nullable=True)

    # Create pinecone_sync_queue
    op.create_table(
        "pinecone_sync_queue",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sqlmodel.AutoString(),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "attempts", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_check_constraint(
        "ck_psq_status",
        "pinecone_sync_queue",
        "status IN ('pending', 'synced', 'failed')",
    )
    op.create_index("ix_psq_status", "pinecone_sync_queue", ["status"])


def downgrade() -> None:
    op.drop_index("ix_psq_status", table_name="pinecone_sync_queue")
    op.drop_table("pinecone_sync_queue")
    op.drop_column("job", "raw_duration_text")
    op.drop_column("job", "inferred_timezone")
    op.drop_column("job", "raw_datetime_text")
    op.drop_column("job", "pay_type")
    op.alter_column("job", "pay_rate", existing_type=sa.Float(), nullable=False)
