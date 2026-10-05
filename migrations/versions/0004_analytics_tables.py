"""analytics tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-05 08:30:37.574301
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_event",
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("app_event", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_app_event_ts"), ["ts"], unique=False)

    op.create_table(
        "dashboard",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("layouts", sa.JSON(), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "sleeve",
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("target_pct", sa.String(), nullable=True),
        sa.Column("band_pct", sa.String(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "watchlist",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "widget",
        sa.Column("dashboard_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("grid", sa.JSON(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["dashboard_id"],
            ["dashboard.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("widget", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_widget_dashboard_id"), ["dashboard_id"], unique=False)

    op.create_table(
        "watchlist_item",
        sa.Column("watchlist_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instrument.id"],
        ),
        sa.ForeignKeyConstraint(
            ["watchlist_id"],
            ["watchlist.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("watchlist_id", "instrument_id"),
    )
    with op.batch_alter_table("watchlist_item", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_watchlist_item_watchlist_id"), ["watchlist_id"], unique=False
        )

    op.create_table(
        "quote",
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("price", sa.String(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["listing_id"],
            ["listing.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("quote", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_quote_listing_id"), ["listing_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_quote_ts"), ["ts"], unique=False)

    with op.batch_alter_table("account", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("track_cash", sa.Boolean(), server_default="0", nullable=False)
        )

    with op.batch_alter_table("instrument", schema=None) as batch_op:
        batch_op.add_column(sa.Column("region", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("sector", sa.String(length=60), nullable=True))
        batch_op.add_column(sa.Column("sleeve_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("is_benchmark", sa.Boolean(), server_default="0", nullable=False)
        )
        batch_op.create_foreign_key("fk_instrument_sleeve_id", "sleeve", ["sleeve_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("instrument", schema=None) as batch_op:
        batch_op.drop_constraint("fk_instrument_sleeve_id", type_="foreignkey")
        batch_op.drop_column("is_benchmark")
        batch_op.drop_column("sleeve_id")
        batch_op.drop_column("sector")
        batch_op.drop_column("region")

    with op.batch_alter_table("account", schema=None) as batch_op:
        batch_op.drop_column("track_cash")

    with op.batch_alter_table("quote", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_quote_ts"))
        batch_op.drop_index(batch_op.f("ix_quote_listing_id"))

    op.drop_table("quote")
    with op.batch_alter_table("watchlist_item", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_watchlist_item_watchlist_id"))

    op.drop_table("watchlist_item")
    with op.batch_alter_table("widget", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_widget_dashboard_id"))

    op.drop_table("widget")
    op.drop_table("watchlist")
    op.drop_table("sleeve")
    op.drop_table("dashboard")
    with op.batch_alter_table("app_event", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_app_event_ts"))

    op.drop_table("app_event")
