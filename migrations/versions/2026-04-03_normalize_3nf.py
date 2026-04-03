"""normalize_3nf — remove transitive user_id columns, drop stale rate_limit constraint, enforce audit_log invariant"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Remove transitive user_id from job (3NF Violation 1)
    op.drop_constraint("job_user_id_fkey", "job", type_="foreignkey")
    op.drop_column("job", "user_id")

    # 2. Remove transitive user_id from work_request (3NF Violation 2)
    op.drop_constraint(
        "work_request_user_id_fkey", "work_request", type_="foreignkey"
    )
    op.drop_column("work_request", "user_id")

    # 3. Drop stale unique constraint on rate_limit (schema correctness)
    op.drop_constraint(
        "uq_rate_limit_user_window", "rate_limit", type_="unique"
    )

    # 4. Add non-unique composite index for rolling-window COUNT query
    op.create_index(
        "ix_rate_limit_user_created_at",
        "rate_limit",
        ["user_id", "created_at"],
    )

    # 5. Enforce audit_log invariant: message_sid must be present when
    #    message_id is populated
    op.create_check_constraint(
        "ck_audit_log_message_sid_consistent",
        "audit_log",
        "message_id IS NULL OR message_sid IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_audit_log_message_sid_consistent", "audit_log", type_="check"
    )
    op.drop_index("ix_rate_limit_user_created_at", table_name="rate_limit")
    op.create_unique_constraint(
        "uq_rate_limit_user_window", "rate_limit", ["user_id", "created_at"]
    )
    # Restore work_request.user_id as nullable (original NOT NULL cannot be
    # restored without data — documented limitation, treat as one-way)
    op.add_column(
        "work_request",
        sa.Column("user_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "work_request_user_id_fkey",
        "work_request",
        "user",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "job",
        sa.Column("user_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "job_user_id_fkey",
        "job",
        "user",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
