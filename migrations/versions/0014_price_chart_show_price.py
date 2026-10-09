"""price chart widgets list the price among what they show

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-09 12:00:00.000000
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rewrite(change: str) -> None:
    """Add (or remove) "price" in the `overlays` of every stored price chart. The price used to
    be implied; it is now one of the things the chart shows, so that it can be left out."""
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, config FROM widget WHERE type = 'price_chart'")).all()
    for widget_id, raw in rows:
        config = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        overlays = list(config.get("overlays") or [])
        if change == "add" and "price" not in overlays:
            overlays.insert(0, "price")
        elif change == "remove":
            overlays = [o for o in overlays if o not in ("price", "changes", "since_start")]
        else:
            continue
        config["overlays"] = overlays
        bind.execute(
            sa.text("UPDATE widget SET config = :config WHERE id = :id"),
            {"config": json.dumps(config), "id": widget_id},
        )


def upgrade() -> None:
    _rewrite("add")


def downgrade() -> None:
    _rewrite("remove")
