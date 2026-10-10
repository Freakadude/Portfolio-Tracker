"""news: what a story could mean later, and whether it touches the owner at all

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-10 12:00:00.000000

Four columns on the assessment (term, level, outlook text, advice) and one on the story
(`affects_owner`). The flag is worked out for the stories already stored, and stories seen in the
last seven days are marked as not assessed so the news job assesses them again with the new
prompt, in its normal batches and under the monthly budget (ADR 0061).
"""

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SLEEVE_MIN_IMPACT = 20  # the same rule as folio/news/service.py effect_of


def _affected(raw: object) -> list[object]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    return list(raw) if isinstance(raw, list) else []


def upgrade() -> None:
    op.add_column("news_assessment", sa.Column("outlook_term", sa.String(6), nullable=True))
    op.add_column("news_assessment", sa.Column("outlook_level", sa.String(6), nullable=True))
    op.add_column("news_assessment", sa.Column("outlook", sa.Text(), nullable=True))
    op.add_column("news_assessment", sa.Column("advice", sa.Text(), nullable=True))
    op.add_column(
        "news_cluster",
        sa.Column("affects_owner", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    bind = op.get_bind()
    latest = {}
    for row in bind.execute(
        sa.text("SELECT cluster_id, impact_score, affected FROM news_assessment ORDER BY id")
    ):
        latest[row[0]] = (row[1], _affected(row[2]))
    links: dict[int, list[tuple[object, object, str]]] = {}
    for row in bind.execute(
        sa.text("SELECT cluster_id, instrument_id, sleeve, matched_by FROM news_link")
    ):
        links.setdefault(row[0], []).append((row[1], row[2], row[3] or ""))
    for (cluster_id,) in bind.execute(sa.text("SELECT id FROM news_cluster")).all():
        own = [k for k in links.get(cluster_id, []) if k[0] is not None or k[1]]
        if not own:
            continue
        found = latest.get(cluster_id)
        if found is None:
            effect = True
        else:
            impact, affected = found
            effect = (
                bool(affected)
                or any(k[2].startswith("llm:") for k in own)
                or (any(k[1] for k in own) and impact >= SLEEVE_MIN_IMPACT)
            )
        if effect:
            bind.execute(
                sa.text("UPDATE news_cluster SET affects_owner = 1 WHERE id = :id"),
                {"id": cluster_id},
            )
    since = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    bind.execute(
        sa.text("UPDATE news_cluster SET assessed = 0 WHERE assessed = 1 AND last_seen >= :since"),
        {"since": since},
    )


def downgrade() -> None:
    op.drop_column("news_cluster", "affects_owner")
    op.drop_column("news_assessment", "advice")
    op.drop_column("news_assessment", "outlook")
    op.drop_column("news_assessment", "outlook_level")
    op.drop_column("news_assessment", "outlook_term")
