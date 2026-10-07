"""talks with the strategy helper

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-07 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assistant_session",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("mode", sa.String(length=6), nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=True),
        sa.Column("messages", sa.JSON(), nullable=False),
        sa.Column("draft_yaml", sa.Text(), nullable=True),
        sa.Column("spent_eur", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategy.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("assistant_session", schema=None) as batch_op:
        batch_op.create_index("ix_assistant_session_strategy_id", ["strategy_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("assistant_session", schema=None) as batch_op:
        batch_op.drop_index("ix_assistant_session_strategy_id")
    op.drop_table("assistant_session")
