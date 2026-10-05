"""event calendar

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-06 02:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "calendar_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("kind", sa.String(length=14), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("external_id", sa.String(length=80), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("brief_sent_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["instrument_id"], ["instrument.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("calendar_event", schema=None) as batch_op:
        batch_op.create_index("ix_calendar_event_event_date", ["event_date"], unique=False)
        batch_op.create_index("ix_calendar_event_external_id", ["external_id"], unique=False)
        batch_op.create_index("ix_calendar_event_instrument_id", ["instrument_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("calendar_event", schema=None) as batch_op:
        batch_op.drop_index("ix_calendar_event_instrument_id")
        batch_op.drop_index("ix_calendar_event_external_id")
        batch_op.drop_index("ix_calendar_event_event_date")
    op.drop_table("calendar_event")
