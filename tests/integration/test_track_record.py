"""The track record (FR-AG-06): recommendations are compared with later closes by the daily job,
and the API reports hit rates by action type."""

import datetime as dt
from collections.abc import Callable
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from folio.agent.runs import finish_run, start_run
from folio.agent.trackrecord import measure_due
from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models_insight import Recommendation
from folio.db.models_ledger import PriceBar
from folio.jobs.agent import outcomes_job
from tests.conftest import PASSWORD, USERNAME
from tests.integration.test_agent_run import job_ctx
from tests.marketdata_helpers import make_listing

D = Decimal
CREATED = dt.datetime(2026, 8, 1, 20, 0, tzinfo=dt.UTC)
TODAY = dt.date(2026, 10, 5)  # 65 days after: the +7 and +30 marks have passed, +90 has not


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


@pytest.fixture
def instrument(db: Session) -> str:
    """An instrument whose close was 100 on the day of the advice, 102 a week later and 98 a month
    later."""
    inst, listing = make_listing(db, ticker="OUT")
    for day, close in (("2026-07-31", "100"), ("2026-08-07", "102"), ("2026-08-31", "98")):
        db.add(
            PriceBar(
                listing_id=listing.id,
                date=dt.date.fromisoformat(day),
                open=D(close),
                high=D(close),
                low=D(close),
                close=D(close),
                volume=0,
                source="fake",
            )
        )
    db.commit()
    return str(inst.name)


def advice(
    db: Session,
    action: str,
    subjects: list[str],
    prices: dict[str, str],
    status: str = "new",
    created: dt.datetime = CREATED,
) -> Recommendation:
    run = start_run(db, "daily", "daily_review", "test-model", "system@1+x", created)
    finish_run(db, run, created, "ok")
    rec = Recommendation(
        run_id=run.id,
        action_type=action,
        severity="low",
        subjects=subjects,
        title=f"{action} {subjects}",
        summary="s",
        rationale="r",
        evidence=[],
        sources=[],
        confidence="medium",
        expires_at=created + dt.timedelta(days=14),
        status=status,
        price_at_creation=prices,
        created_at=created,
    )
    db.add(rec)
    db.commit()
    return rec


def test_the_job_fills_each_horizon_once_its_day_and_its_price_are_there(
    db: Session, instrument: str, settings: Settings
) -> None:
    buy = advice(db, "direct_contribution", [instrument], {instrument: "100"})
    trim = advice(db, "trim", [instrument], {instrument: "100"})
    watch = advice(db, "watch", [instrument], {instrument: "100"}, status="seen")
    result = outcomes_job(job_ctx(settings, None, dt.datetime(2026, 10, 5, 21, tzinfo=dt.UTC)))
    assert result.status == "ok" and "6 outcome(s) measured" in result.log
    db.expire_all()
    assert sorted(buy.outcome) == ["d30", "d7"]  # +90 is not due before 30 October
    assert (buy.outcome["d7"]["return"], buy.outcome["d7"]["hit"]) == ("0.020000", True)
    assert (buy.outcome["d30"]["return"], buy.outcome["d30"]["hit"]) == ("-0.020000", False)
    assert (trim.outcome["d7"]["hit"], trim.outcome["d30"]["hit"]) == (False, True)
    assert watch.outcome["d7"]["return"] == "0.020000" and watch.outcome["d7"]["hit"] is None


def test_measuring_twice_changes_nothing_and_refused_items_are_ignored(
    db: Session, instrument: str
) -> None:
    advice(db, "direct_contribution", [instrument], {instrument: "100"})
    refused = advice(db, "trim", [instrument], {instrument: "100"}, status="refused")
    assert measure_due(db, TODAY) == 2
    assert measure_due(db, TODAY) == 0
    db.refresh(refused)
    assert refused.outcome == {}


def test_a_horizon_without_a_price_waits_and_is_then_closed_as_no_price(
    db: Session, instrument: str
) -> None:
    rec = advice(db, "direct_contribution", [instrument], {instrument: "100"})
    # the +90 mark is 30 October and no close is near it: it waits through the 14 grace days
    assert measure_due(db, dt.date(2026, 10, 31)) == 2  # only +7 and +30
    assert "d90" not in rec.outcome
    assert measure_due(db, dt.date(2026, 11, 13)) == 0  # 30 October + 14 days: still waiting
    assert measure_due(db, dt.date(2026, 11, 14)) == 1
    db.refresh(rec)
    assert rec.outcome["d90"]["note"] == "no price" and rec.outcome["d90"]["hit"] is None


def test_advice_about_something_that_is_not_an_instrument_has_nothing_to_compare(
    db: Session,
) -> None:
    rec = advice(db, "direct_contribution", ["the whole portfolio"], {})
    assert measure_due(db, TODAY) == 2
    db.refresh(rec)
    assert rec.outcome["d7"]["note"] == "no price" and rec.outcome["d7"]["return"] is None


@pytest.fixture
def api(make_client: Callable[..., TestClient], owner: None) -> TestClient:
    c = make_client()
    c.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return c


def test_the_track_record_lists_hit_rate_by_action_type_and_by_decision(
    api: TestClient, db: Session, instrument: str
) -> None:
    advice(db, "direct_contribution", [instrument], {instrument: "100"}, status="accepted")
    advice(db, "direct_contribution", [instrument], {instrument: "104"}, status="rejected")
    advice(db, "trim", [instrument], {instrument: "100"}, status="rejected")
    advice(db, "watch", [instrument], {instrument: "100"}, status="seen")
    measure_due(db, TODAY)
    db.commit()
    body = api.get("/api/v1/agent/track-record").json()
    assert body["total"] == 4 and body["decision_horizon"] == 30
    assert "Price only" in body["note"] and "small samples" in body["note"]
    by = {a["action_type"]: a for a in body["actions"]}
    buy30 = next(h for h in by["direct_contribution"]["by_horizon"] if h["days"] == 30)
    # at +30 the close is 98: from 100 that is a miss for a contribution, and from 104 as well
    assert (buy30["measured"], buy30["scored"], buy30["hits"]) == (2, 2, 0)
    assert D(buy30["hit_rate"]) == 0
    trim30 = next(h for h in by["trim"]["by_horizon"] if h["days"] == 30)
    assert (trim30["hits"], D(trim30["hit_rate"])) == (1, 1)  # the price did not rise
    watch30 = next(h for h in by["watch"]["by_horizon"] if h["days"] == 30)
    assert (watch30["measured"], watch30["scored"], watch30["hit_rate"]) == (1, 0, None)
    assert by["watch"]["scored_type"] is False
    decisions = {d["decision"]: d for d in body["decisions"]}
    assert decisions["accepted"]["count"] == 1 and decisions["rejected"]["count"] == 2
    assert api.get("/api/v1/agent/track-record?horizon=7").json()["decision_horizon"] == 7
    assert api.get("/api/v1/agent/track-record?horizon=5").status_code == 422


def test_the_track_record_needs_a_login(client: TestClient, owner: None) -> None:
    assert client.get("/api/v1/agent/track-record").status_code == 401
