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


def test_the_ask_widget_says_whether_the_agent_is_on_and_keeps_its_option(
    api: TestClient, db: Session, world
) -> None:
    on = widget(api, "ask", {"show_last": 5})
    assert on == {"empty": False, "reason": None, "show_last": 5}
    api.put("/api/v1/settings/agent", json={"enabled": False})
    off = widget(api, "ask")
    assert off["empty"] is True and "switched off" in off["reason"] and off["show_last"] == 3
    bad = api.post(
        "/api/v1/widgets/data",
        json={
            "as_of": NOW.date().isoformat(),
            "filters": {},
            "requests": [{"key": "w", "type": "ask", "config": {"show_last": 99}}],
        },
    ).json()["results"]["w"]
    assert bad["error"]


def test_the_projection_widget_shows_its_assumptions_and_a_band(
    api: TestClient, db: Session, world
) -> None:
    out = widget(
        api,
        "projection",
        {"years": 2, "monthly_contribution": "100", "return_pct": "0", "volatility_pct": "0"},
    )
    assert out["assumptions"]["years"] == 2 and out["assumptions"]["annual_return_pct"] == "0"
    assert out["assumptions"]["start_value_eur"].startswith("2500")
    first, last = out["points"][0], out["points"][-1]
    assert first["median"].startswith("2500") and last["invested"].startswith("4900")
    assert last["p10"] == last["median"] == last["p90"]  # no volatility: no band
    assert len(out["points"]) == 25  # a point a month for a short horizon
    long = widget(api, "projection", {"years": 30})
    assert len(long["points"]) == 121  # every third month for a long one, and the last
    bad = api.post(
        "/api/v1/widgets/data",
        json={
            "as_of": NOW.date().isoformat(),
            "filters": {},
            "requests": [{"key": "w", "type": "projection", "config": {"years": 99}}],
        },
    ).json()["results"]["w"]
    assert bad["error"]
