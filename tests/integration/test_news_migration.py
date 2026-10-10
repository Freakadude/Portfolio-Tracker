"""Migration 0015 (ADR 0061): a story that touches nothing is flagged so it is no longer listed,
and the stories of the last seven days are put back to be assessed with the new prompt."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alembic import command

from folio.db import migrate

NOW = datetime.now(UTC)


def stamp(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S.000000")


def test_the_flag_is_worked_out_for_stored_stories_and_recent_ones_are_assessed_again(
    tmp_path: Path,
) -> None:
    url = f"sqlite:///{tmp_path / 'old.db'}"
    command.upgrade(migrate._config(url), "0014")
    con = sqlite3.connect(tmp_path / "old.db")
    now = stamp(0)

    def cluster(n: int, title: str, days_ago: float, assessed: int) -> None:
        con.execute(
            "INSERT INTO news_cluster (id, created_at, updated_at, title, first_seen, last_seen, relevance, "
            "linked, assessed) VALUES (?, ?, ?, ?, ?, ?, '0.5', 1, ?)",
            (n, now, now, title, stamp(days_ago), stamp(days_ago), assessed),
        )

    def link(n: int, instrument: int | None, sleeve: str | None, matched_by: str) -> None:
        con.execute(
            "INSERT INTO news_link (cluster_id, created_at, updated_at, instrument_id, sleeve, link_type, "
            "relevance, matched_by) VALUES (?, ?, ?, ?, ?, 'direct', '0.5', ?)",
            (n, now, now, instrument, sleeve, matched_by),
        )

    def assessment(n: int, impact: int, affected: list[str]) -> None:
        con.execute(
            "INSERT INTO news_assessment (cluster_id, created_at, updated_at, impact_score, direction, horizon, "
            "affected, rationale, confidence, model, cost_eur) "
            "VALUES (?, ?, ?, ?, 'mixed', 'days', ?, 'r', 'medium', 'm', '0')",
            (n, now, now, impact, json.dumps(affected)),
        )

    cluster(1, "names a holding", 1, 1)  # assessed, affects a holding -> shown, assessed again
    link(1, 3, None, "alias:asml")
    assessment(1, 60, ["instrument:3"])
    cluster(2, "touches nothing", 2, 1)  # assessed, nothing affected -> not shown
    link(2, 3, None, "alias:asml")
    assessment(2, 5, [])
    cluster(3, "model added a link", 3, 1)  # nothing named, but the model linked it -> shown
    link(3, None, "gold_hedge", "llm:theme:rates matter")
    assessment(3, 10, [])
    cluster(4, "waiting to be assessed", 1, 0)  # linked, not assessed -> shown
    link(4, 5, None, "isin:X")
    cluster(5, "no links at all", 1, 0)  # -> not shown
    cluster(6, "macro story, sleeve reached, real score", 20, 1)  # old: not assessed again
    link(6, None, "gold_hedge", "macro:DFF")
    assessment(6, 55, [])
    cluster(7, "macro story, noise", 20, 1)
    link(7, None, "gold_hedge", "macro:DFF")
    assessment(7, 3, [])
    con.commit()
    con.close()

    command.upgrade(migrate._config(url), "0015")

    con = sqlite3.connect(tmp_path / "old.db")
    flags = dict(con.execute("SELECT id, affects_owner FROM news_cluster"))
    assert flags == {1: 1, 2: 0, 3: 1, 4: 1, 5: 0, 6: 1, 7: 0}
    again = dict(con.execute("SELECT id, assessed FROM news_cluster"))
    assert again == {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 1, 7: 1}  # the last 7 days only
    columns = {r[1] for r in con.execute("PRAGMA table_info(news_assessment)")}
    assert {"outlook_term", "outlook_level", "outlook", "advice"} <= columns
    con.close()

    command.downgrade(migrate._config(url), "0014")
    con = sqlite3.connect(tmp_path / "old.db")
    assert "advice" not in {r[1] for r in con.execute("PRAGMA table_info(news_assessment)")}
    assert "affects_owner" not in {r[1] for r in con.execute("PRAGMA table_info(news_cluster)")}
