"""Convert money columns from float dollars to integer cents

Revision ID: 006
Revises: 005
Create Date: 2026-04-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # job.pay_rate: FLOAT dollars → INTEGER cents
    op.alter_column(
        "job",
        "pay_rate",
        existing_type=sa.Float(),
        type_=sa.Integer(),
        existing_nullable=True,
        postgresql_using="ROUND(pay_rate * 100)::INTEGER",
    )

    # work_goal.target_earnings: FLOAT dollars → INTEGER cents
    op.alter_column(
        "work_goal",
        "target_earnings",
        existing_type=sa.Float(),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="ROUND(target_earnings * 100)::INTEGER",
    )


def downgrade() -> None:
    op.alter_column(
        "work_goal",
        "target_earnings",
        existing_type=sa.Integer(),
        type_=sa.Float(),
        existing_nullable=False,
    )

    op.alter_column(
        "job",
        "pay_rate",
        existing_type=sa.Integer(),
        type_=sa.Float(),
        existing_nullable=True,
    )
