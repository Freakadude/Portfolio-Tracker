# ruff: noqa: F811  (the fixtures are imported from other test modules and used as parameters)
"""Backtesting a rule on a real book through the API (FR-ST-06): the drift rule over the history
shows its dates and drift values."""

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.db.models_insight import Recommendation
from folio.db.models_strategy import Signal, Strategy
from tests.conftest import PASSWORD, USERNAME
from tests.integration.test_agent_run import world  # noqa: F401
from tests.integration.test_news_pipeline import NOW, book, db  # noqa: F401

D = Decimal


@pytest.fixture
def api(make_client: Callable[..., TestClient], owner: None) -> TestClient:
    c = make_client()
    c.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return c


def active_id(db: Session) -> int:
    return db.scalars(select(Strategy).where(Strategy.mode == "active")).one().id


def tuesdays(first: date, last: date) -> list[str]:
    out, day = [], first
    while day <= last:
        out.append(day.isoformat())
        day += timedelta(days=7)
    return out


def test_a_drift_rule_over_the_book_lists_its_dates_and_drift_values(
    api: TestClient, db: Session, world
) -> None:
    # World ETF + ASML 60 %, gold 40 % since the first purchase; the strategy wants 40 and 60
    r = api.post(
        f"/api/v1/strategies/{active_id(db)}/backtest",
        json={"start": "2024-01-01", "end": NOW.date().isoformat()},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["strategy"], body["version"], body["end"]) == ("Run test", 1, "2024-03-15")
    assert body["days_checked"] == 54  # the weekdays from 2 January; nothing was held on the 1st
    gold = [f for f in body["firings"] if f["subject"] == "gold_hedge"]
    assert [f["date"] for f in gold] == tuesdays(
        date(2024, 1, 2), date(2024, 3, 12)
    )  # each cooldown
    assert {D(f["value"]) for f in gold} == {D(20)}  # 20 pp under its target, a hard breach
    assert {f["severity"] for f in gold} == {"high"} and {f["rule_id"] for f in gold} == {"drift"}
    assert "20.0 pp under" in gold[0]["message"]
    assert len([f for f in body["firings"] if f["subject"] == "equity"]) == 11
    (rule,) = body["rules"]
    assert (rule["rule_id"], rule["backtestable"], rule["days_true"], rule["fired"]) == (
        "drift",
        True,
        54 * 2,  # both sleeves, every day
        22,
    )
    assert "Nothing is saved" in body["note"]


def test_nothing_is_saved_or_sent_by_a_backtest(api: TestClient, db: Session, world) -> None:
    before = (
        len(db.scalars(select(Signal)).all()),
        len(db.scalars(select(Recommendation)).all()),
    )
    api.post(f"/api/v1/strategies/{active_id(db)}/backtest", json={"end": "2024-03-15"})
    db.expire_all()
    after = (
        len(db.scalars(select(Signal)).all()),
        len(db.scalars(select(Recommendation)).all()),
    )
    assert after == before  # the world's one signal is all there is


def test_a_chosen_rule_and_a_shorter_range_narrow_the_list(
    api: TestClient, db: Session, world
) -> None:
    sid = active_id(db)
    body = api.post(
        f"/api/v1/strategies/{sid}/backtest",
        json={"rule_ids": ["drift"], "start": "2024-02-01", "end": "2024-02-15"},
    ).json()
    assert body["days_checked"] == 11
    assert {f["date"] for f in body["firings"]} == {
        "2024-02-01",
        "2024-02-08",
        "2024-02-15",
    }  # fresh at the start of the range
    default_range = api.post(f"/api/v1/strategies/{sid}/backtest", json={}).json()
    assert default_range["end"] == date.today().isoformat()  # a year back from today


def test_bad_requests_are_explained(api: TestClient, db: Session, world) -> None:
    sid = active_id(db)
    url = f"/api/v1/strategies/{sid}/backtest"
    backwards = api.post(url, json={"start": "2024-03-01", "end": "2024-02-01"})
    assert backwards.status_code == 422 and "before its start" in backwards.json()["detail"]
    long = api.post(url, json={"start": "2020-01-01", "end": "2024-03-15"})
    assert long.status_code == 422 and "at most 1100 days" in long.json()["detail"]
    unknown = api.post(url, json={"rule_ids": ["nope"]})
    assert unknown.status_code == 422 and "no rule nope" in unknown.json()["detail"]
    assert api.post("/api/v1/strategies/9999/backtest", json={}).status_code == 404
    assert api.post(url, json={"colour": "red"}).status_code == 422


def test_a_portfolio_without_history_says_so(api: TestClient, db: Session) -> None:
    from folio.strategies import service as strategies
    from tests.integration.test_agent_run import YAML

    created = strategies.create(db, strategies.read_input(YAML, None))
    db.commit()
    body = api.post(f"/api/v1/strategies/{created.id}/backtest", json={}).json()
    assert body["days_checked"] == 0 and body["firings"] == []
    assert body["notes"] == ["The portfolio has no history yet."]


def test_a_backtest_needs_a_login(client: TestClient, owner: None) -> None:
    assert client.post("/api/v1/strategies/1/backtest", json={}).status_code == 401
