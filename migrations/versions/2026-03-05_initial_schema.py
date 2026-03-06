"""initial_schema

Revision ID: 001
Revises:
Create Date: 2026-03-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "phone",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("phone_hash", sqlmodel.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_phone_phone_hash"), "phone", ["phone_hash"], unique=True)

    op.create_table(
        "inbound_message",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message_sid", sqlmodel.AutoString(), nullable=False),
        sa.Column("phone_hash", sqlmodel.AutoString(), nullable=False),
        sa.Column("body", sqlmodel.AutoString(), nullable=False),
        sa.Column("raw_sms", sqlmodel.AutoString(), nullable=False),
        sa.Column("raw_gpt_response", sqlmodel.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_inbound_message_message_sid"),
        "inbound_message",
        ["message_sid"],
        unique=True,
    )
    op.create_index(
        op.f("ix_inbound_message_phone_hash"),
        "inbound_message",
        ["phone_hash"],
        unique=False,
    )

    op.create_table(
        "rate_limit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("phone_hash", sqlmodel.AutoString(), nullable=False),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "phone_hash",
            "window_start",
            name="uq_rate_limit_phone_window",
        ),
    )
    op.create_index(
        op.f("ix_rate_limit_phone_hash"),
        "rate_limit",
        ["phone_hash"],
        unique=False,
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message_sid", sqlmodel.AutoString(), nullable=False),
        sa.Column("event", sqlmodel.AutoString(), nullable=False),
        sa.Column("detail", sqlmodel.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_audit_log_message_sid"),
        "audit_log",
        ["message_sid"],
        unique=False,
    )

    op.create_table(
        "job",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("phone_hash", sqlmodel.AutoString(), nullable=False),
        sa.Column("description", sqlmodel.AutoString(), nullable=True),
        sa.Column("location", sqlmodel.AutoString(), nullable=True),
        sa.Column("pay_rate", sa.Float(), nullable=True),
        sa.Column("estimated_duration_hours", sa.Float(), nullable=True),
        sa.Column("ideal_datetime", sa.DateTime(), nullable=True),
        sa.Column("datetime_flexible", sa.Boolean(), nullable=True),
        sa.Column("raw_sms", sqlmodel.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_job_phone_hash"), "job", ["phone_hash"], unique=False)

    op.create_table(
        "worker",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("phone_hash", sqlmodel.AutoString(), nullable=False),
        sa.Column("target_earnings", sa.Float(), nullable=True),
        sa.Column("target_timeframe", sqlmodel.AutoString(), nullable=True),
        sa.Column("raw_sms", sqlmodel.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_worker_phone_hash"),
        "worker",
        ["phone_hash"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("worker")
    op.drop_table("job")
    op.drop_table("audit_log")
    op.drop_table("rate_limit")
    op.drop_table("inbound_message")
    op.drop_table("phone")
