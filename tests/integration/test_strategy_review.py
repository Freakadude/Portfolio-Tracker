# ruff: noqa: F811  (the fixtures are imported from other test modules and used as parameters)
"""The weekly deep review (FR-AG-07) and the quarterly strategy review (FR-ST-08)."""

import datetime as dt
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.agent.run import run_agent
from folio.config import Settings
from folio.db.models_strategy import Notification, Signal, Strategy, StrategyVersion
from folio.jobs.agent import due_runs
from folio.jobs.strategies import quarterly_review_job
from tests.agent_helpers import ScriptedLlm
from tests.conftest import PASSWORD, USERNAME
from tests.integration.test_agent_run import Brain, job_ctx, settings_save, world  # noqa: F401
from tests.integration.test_news_pipeline import book, db  # noqa: F401

# --- the weekly deep review -----------------------------------------------------------------------

SUNDAY_EVENING = dt.datetime(2024, 3, 17, 17, 30, tzinfo=dt.UTC)  # 18:30 in Amsterdam (CET)


def weekly(db: Session, now: dt.datetime) -> list[tuple[str, str]]:
    return [(d.run_type, d.trigger) for d in due_runs(db, now) if d.run_type == "weekly_review"]


def test_the_weekly_review_is_due_on_sunday_evening_once_a_week(db: Session, world) -> None:
    assert weekly(db, SUNDAY_EVENING) == [("weekly_review", "weekly:2024-W11")]
    assert weekly(db, SUNDAY_EVENING - dt.timedelta(hours=1)) == []  # 17:30, before 18:00
    assert weekly(db, SUNDAY_EVENING - dt.timedelta(days=1)) == []  # Saturday
    assert weekly(db, SUNDAY_EVENING + dt.timedelta(days=1)) == []  # Monday
    run_agent(
        db,
        ScriptedLlm(handler=Brain(compose=lambda calc: [])).client(),
        SUNDAY_EVENING,
        run_type="weekly_review",
        trigger="weekly:2024-W11",
    )
    db.commit()
    assert weekly(db, SUNDAY_EVENING + dt.timedelta(hours=2)) == []  # not twice a week
    assert weekly(db, SUNDAY_EVENING + dt.timedelta(days=7)) == [
        ("weekly_review", "weekly:2024-W12")
    ]
    settings_save(db, weekly_review_time="21:00")
    assert weekly(db, SUNDAY_EVENING + dt.timedelta(days=7)) == []  # 18:30 is before 21:00 now
    settings_save(db, enabled=False)
    assert weekly(db, SUNDAY_EVENING + dt.timedelta(days=14)) == []


def test_the_weekly_review_uses_the_strong_model_and_leaves_a_digest(db: Session, world) -> None:
    llm = ScriptedLlm(handler=Brain(compose=lambda calc: []))
    run_agent(db, llm.client(), SUNDAY_EVENING, run_type="weekly_review", trigger="weekly:2024-W11")
    db.commit()
    assert {r["model"] for r in llm.requests} == {"claude-opus-5-5"}
    digest = db.scalars(select(Notification).where(Notification.subject == "weekly_review digest"))
    (item,) = list(digest)
    assert item.title.startswith("Weekly review:") and item.source == "agent"


# --- the quarterly strategy review ----------------------------------------------------------------

AFTER_Q1 = dt.datetime(2024, 4, 2, 6, 0, tzinfo=dt.UTC)


def own_the_signal(db: Session) -> None:
    """The world's drift signal stands in for one the active strategy fired (a price alert has no
    strategy version and is not part of the review)."""
    version = db.scalar(
        select(StrategyVersion.id)
        .join(Strategy, Strategy.id == StrategyVersion.strategy_id)
        .where(Strategy.mode == "active")
    )
    for signal in db.scalars(select(Signal)):
        signal.strategy_version_id = version
    db.commit()


def reviews(db: Session) -> list[Notification]:
    return list(db.scalars(select(Notification).where(Notification.subject.like("review:%"))))


def test_a_finished_quarter_gets_one_inbox_item_however_often_the_job_runs(
    db: Session, world, settings: Settings
) -> None:
    own_the_signal(db)
    ctx = job_ctx(settings, None, AFTER_Q1)
    first = quarterly_review_job(ctx)
    assert first.status == "ok" and "Review of 2024Q1 posted" in first.log
    db.expire_all()
    (item,) = reviews(db)
    assert (item.source, item.subject, item.severity) == ("digest", "review:2024Q1", "info")
    assert item.link == "/strategies/review?quarter=2024Q1"
    assert "gold_hedge (target 60%)" in item.body and "-20.0 pp" in item.body
    assert "Signals that fired: drift 1x (worst medium)." in item.body
    second = quarterly_review_job(ctx)
    assert "already has its review" in second.log
    db.expire_all()
    assert len(reviews(db)) == 1


def test_the_job_waits_for_the_quarter_to_end(db: Session, world, settings: Settings) -> None:
    during = job_ctx(settings, None, dt.datetime(2024, 3, 20, 6, 0, tzinfo=dt.UTC))
    assert "2024Q1 is not over yet" in quarterly_review_job(during, "2024Q1").log
    db.expire_all()
    assert reviews(db) == []


def test_without_an_active_strategy_there_is_nothing_to_review(
    db: Session, settings: Settings
) -> None:
    result = quarterly_review_job(job_ctx(settings, None, AFTER_Q1))
    assert result.status == "ok" and "No active strategy" in result.log
    assert reviews(db) == []


@pytest.fixture
def api(make_client: Callable[..., TestClient], owner: None) -> TestClient:
    c = make_client()
    c.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return c


def test_the_review_page_data_and_the_post_button(api: TestClient, db: Session, world) -> None:
    own_the_signal(db)
    body = api.get("/api/v1/strategy-review?quarter=2024Q1").json()
    assert (body["quarter"], body["complete"], body["strategy"]) == (
        "2024Q1",
        True,
        "Run test",
    )
    gold = next(s for s in body["sleeves"] if s["id"] == "gold_hedge")
    assert [p["day"] for p in gold["month_ends"]] == ["2024-01-31", "2024-02-29", "2024-03-31"]
    assert float(gold["worst"]["drift_pp"]) == -20.0
    assert body["signals"] == [{"rule_id": "drift", "count": 1, "worst_severity": "medium"}]
    assert body["text"].startswith("Quarterly review of Run test, 2024Q1")

    first = api.post("/api/v1/strategy-review/post?quarter=2024Q1").json()
    again = api.post("/api/v1/strategy-review/post?quarter=2024Q1").json()
    assert (first["posted"], again["posted"]) == (True, False)
    current = api.post("/api/v1/strategy-review/post?quarter=2999Q4")
    assert current.status_code == 409 and "ends on" in current.json()["detail"]
    assert api.get("/api/v1/strategy-review?quarter=nonsense").status_code == 422


def test_the_review_needs_an_active_strategy_and_a_login(
    api: TestClient, client: TestClient
) -> None:
    assert api.get("/api/v1/strategy-review?quarter=2024Q1").status_code == 404
    client.cookies.clear()
    assert client.get("/api/v1/strategy-review").status_code == 401
