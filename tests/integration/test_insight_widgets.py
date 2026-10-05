# ruff: noqa: F811  (the fixtures are imported from other test modules and used as parameters)
"""The News and Signals widgets (FR-NW-07, FR-ST-04, FR-AG-05) on a real book."""

import datetime as dt
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.agent.run import run_agent
from folio.db.models_insight import NewsAssessment, NewsCluster, Recommendation
from folio.news.pipeline import cluster_and_link
from tests.agent_helpers import ScriptedLlm
from tests.conftest import PASSWORD, USERNAME
from tests.integration.test_agent_run import Brain, world  # noqa: F401
from tests.integration.test_news_pipeline import NOW, book, db, source, story  # noqa: F401


@pytest.fixture
def api(make_client: Callable[..., TestClient], owner: None) -> TestClient:
    c = make_client()
    c.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return c


def widget(api: TestClient, kind: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    body = {
        "as_of": NOW.date().isoformat(),
        "filters": {},
        "requests": [{"key": "w", "type": kind, "config": config or {}}],
    }
    out = api.post("/api/v1/widgets/data", json=body).json()["results"]["w"]
    assert out["error"] is None, out["error"]
    return out["data"]  # type: ignore[no-any-return]


def test_the_news_feed_lists_linked_stories_with_their_assessment(
    api: TestClient, db: Session, world
) -> None:
    story(db, source(db, "WireA"), "ASML raises outlook on strong chip orders", hours_ago=3)
    story(
        db, source(db, "WireB"), "Parliament debates new fishing quotas", hours_ago=1
    )  # linked to nothing
    cluster_and_link(db, NOW)
    cluster = db.scalar(select(NewsCluster).where(NewsCluster.relevance > 0))
    cluster.assessed, cluster.max_impact = True, 66
    db.add(
        NewsAssessment(
            cluster_id=cluster.id,
            impact_score=66,
            direction="positive",
            horizon="weeks",
            affected=[],
            rationale="r",
            confidence="low",
            model="m",
        )
    )
    db.commit()
    out = widget(api, "news_feed")
    assert [(s["title"], s["impact"], s["direction"]) for s in out["stories"]] == [
        ("ASML raises outlook on strong chip orders", 66, "positive")
    ]
    assert "ASML Holding" in out["stories"][0]["links"]
    assert widget(api, "news_feed", {"min_impact": 70})["empty"] is True


def test_the_signals_widget_puts_open_recommendations_before_signals_and_filters_by_severity(
    api: TestClient, db: Session, world
) -> None:
    run_agent(
        db, ScriptedLlm(handler=Brain()).client(), NOW, run_type="daily_review", trigger="daily"
    )
    db.commit()
    items = widget(api, "signals")["items"]
    assert [(i["kind"], i["title"]) for i in items] == [
        ("recommendation", "Direct new money to gold_hedge"),
        ("signal", "gold_hedge is 20.0 pp under its target"),
    ]
    assert all(i["severity"] == "medium" for i in items)
    assert widget(api, "signals", {"severity": "high"})["empty"] is True
    assert len(widget(api, "signals", {"severity": "medium"})["items"]) == 2
    rec = db.scalar(select(Recommendation))
    rec.expires_at = NOW - dt.timedelta(days=1)  # expired: it leaves the widget
    db.commit()
    assert [i["kind"] for i in widget(api, "signals")["items"]] == ["signal"]
