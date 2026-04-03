"""initial_schema

Revision ID: 001
Revises:
Create Date: 2026-03-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — 3NF schema with TIMESTAMPTZ and integer FKs."""

    # 1. user (no FKs)
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("phone_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_phone_hash", "user", ["phone_hash"], unique=True)

    # 2. message (depends on user)
    op.create_table(
        "message",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("message_sid", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("message_type", sa.String(), nullable=True),
        sa.Column("raw_gpt_response", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_message_message_sid", "message", ["message_sid"], unique=True)
    op.create_index("ix_message_user_id", "message", ["user_id"], unique=False)

    # 3. job (depends on user, message)
    op.create_table(
        "job",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("pay_rate", sa.Float(), nullable=False),
        sa.Column("estimated_duration_hours", sa.Float(), nullable=True),
        sa.Column("ideal_datetime", sa.DateTime(timezone=True), nullable=True),
        sa.Column("datetime_flexible", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("pay_rate > 0", name="ck_job_pay_rate_positive"),
        sa.CheckConstraint(
            "estimated_duration_hours IS NULL OR estimated_duration_hours > 0",
            name="ck_job_estimated_duration_positive",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["message_id"], ["message.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", name="uq_job_message_id"),
    )

    # 4. work_goal (depends on user, message)
    op.create_table(
        "work_goal",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("target_earnings", sa.Float(), nullable=False),
        sa.Column("target_timeframe", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "target_earnings > 0", name="ck_work_goal_target_earnings_positive"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["message_id"], ["message.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", name="uq_work_goal_message_id"),
    )

    # 5. match (depends on job, work_goal)
    op.create_table(
        "match",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("work_goal_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["work_goal_id"], ["work_goal.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "work_goal_id", name="uq_match_job_work_goal"),
    )

    # 6. rate_limit (depends on user)
    op.create_table(
        "rate_limit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "created_at", name="uq_rate_limit_user_window"),
    )

    # 7. audit_log (depends on message via nullable FK)
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("message_sid", sa.String(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("event", sa.String(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["message.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_log_message_sid", "audit_log", ["message_sid"], unique=False)


def downgrade() -> None:
    """Downgrade schema — drop tables in reverse FK dependency order."""
    op.drop_table("audit_log")
    op.drop_table("rate_limit")
    op.drop_table("match")
    op.drop_table("work_goal")
    op.drop_table("job")
    op.drop_table("message")
    op.drop_table("user")
