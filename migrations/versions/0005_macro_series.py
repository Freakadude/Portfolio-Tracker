"""macro series

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-05 09:00:32.266679
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "macro_series",
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "macro_point",
        sa.Column("series_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["series_id"],
            ["macro_series.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("series_id", "date"),
    )
    with op.batch_alter_table("macro_point", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_macro_point_series_id"), ["series_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("macro_point", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_macro_point_series_id"))

    op.drop_table("macro_point")
    op.drop_table("macro_series")
