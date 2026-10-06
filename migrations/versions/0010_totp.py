"""second factor: TOTP flags and recovery codes

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-06 03:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("app_user", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(sa.Column("totp_last_step", sa.Integer(), nullable=True))
    op.create_table(
        "recovery_code",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=255), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("recovery_code", schema=None) as batch_op:
        batch_op.create_index("ix_recovery_code_user_id", ["user_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("recovery_code", schema=None) as batch_op:
        batch_op.drop_index("ix_recovery_code_user_id")
    op.drop_table("recovery_code")
    with op.batch_alter_table("app_user", schema=None) as batch_op:
        batch_op.drop_column("totp_last_step")
        batch_op.drop_column("totp_enabled")
