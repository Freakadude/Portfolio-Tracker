"""The rules job end to end: a transaction that breaks a band gives a signal on the next worker
poll, a condition that stays true waits for its cooldown, shadow strategies only log
(FR-ST-02, FR-ST-03, FR-ST-04)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import Account
from folio.db.models_ledger import JobRequest, PriceBar
from folio.db.models_strategy import Signal
from folio.jobs.scheduler import process_job_requests
from folio.jobs.strategies import rules_job
from folio.ledger_service import TransactionIn, create_transaction
from folio.strategies import service
from tests.conftest import PASSWORD, USERNAME
from tests.marketdata_helpers import make_ctx, make_listing

D = Decimal
NOW = datetime(2024, 3, 15, 20, tzinfo=UTC)
YAML = """\
strategy:
  name: {name}
  sleeves:
    - {{ id: equity, members: [IE00B5BMR087], target_pct: 50, soft_band_pp: 5, hard_band_pp: 10 }}
    - {{ id: gold, members: [IE00B4ND3602], target_pct: 50, soft_band_pp: 5, hard_band_pp: 10 }}
  rules:
    - {{ id: drift, type: drift_band, severity: medium, cooldown_days: 7, worsen_step: 5 }}
"""


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


@pytest.fixture
def book(db: Session) -> dict[str, int]:
    """Two instruments priced at 100 every weekday, 10 units of each: exactly 50/50."""
    equity, eq_listing = make_listing(db, ticker="EQ", isin="IE00B5BMR087")
    gold, gold_listing = make_listing(db, ticker="GLD", isin="IE00B4ND3602")
    day = date(2024, 1, 1)
    while day <= NOW.date():
        if day.weekday() < 5:
            for listing in (eq_listing, gold_listing):
                db.add(PriceBar(listing_id=listing.id, date=day, close=D(100), source="test"))
        day += timedelta(days=1)
    account = Account(name="Broker")
    db.add(account)
    db.flush()
    for instrument in (equity, gold):
        buy(db, account.id, instrument.id, 10, date(2024, 1, 2))
    db.commit()
    return {"account": account.id, "equity": equity.id, "gold": gold.id}


def buy(db: Session, account: int, instrument: int, units: int, day: date) -> None:
    create_transaction(
        db,
        TransactionIn(
            account_id=account,
            instrument_id=instrument,
            type="buy",
            trade_date=day,
            quantity=D(units),
            price=D(100),
        ),  # fmt: skip
    )


def strategy(db: Session, name: str, mode: str) -> int:
    created = service.create(db, service.read_input(YAML.format(name=name), None))
    service.set_mode(db, created, mode)
    db.commit()
    return created.id


def signals(db: Session) -> list[Signal]:
    db.expire_all()
    return list(db.scalars(select(Signal).order_by(Signal.id)))


def test_a_transaction_that_breaks_a_band_gives_a_signal_on_the_next_poll(
    settings: Settings, db, book
) -> None:  # type: ignore[no-untyped-def]
    strategy(db, "Core", "active")
    ctx = make_ctx(settings, [], now=NOW)
    process_job_requests(ctx, settings)  # the queue left by the set-up: balanced, nothing fires
    assert signals(db) == []

    buy(db, book["account"], book["equity"], 10, date(2024, 3, 15))  # equity now 2/3: 16.7 pp over
    db.commit()
    assert db.scalar(
        select(JobRequest.id).where(JobRequest.job == "rules", JobRequest.status == "pending")
    )
    process_job_requests(ctx, settings)  # what the worker does every 5 seconds
    fired = signals(db)
    assert {(s.subject, s.severity, s.shadow) for s in fired} == {
        ("equity", "high", False),
        ("gold", "high", False),
    }
    equity = next(s for s in fired if s.subject == "equity")
    assert equity.dedup_key.endswith("drift:equity:hard") and round(equity.value, 1) == D("16.7")
    assert "push" in equity.payload and "trade" in equity.message


def test_a_condition_that_stays_true_waits_for_its_cooldown_or_a_worsening(
    settings: Settings, db, book
) -> None:  # type: ignore[no-untyped-def]
    strategy(db, "Core", "active")
    buy(db, book["account"], book["equity"], 10, date(2024, 3, 1))
    db.commit()
    assert rules_job(make_ctx(settings, [], now=NOW)).status == "ok"
    assert len(signals(db)) == 2
    rules_job(make_ctx(settings, [], now=NOW + timedelta(days=3)))
    assert len(signals(db)) == 2  # still outside, still within the cooldown: quiet

    buy(db, book["account"], book["equity"], 10, date(2024, 3, 1))  # 75%: worse by 8.3 pp >= 5
    db.commit()
    rules_job(make_ctx(settings, [], now=NOW + timedelta(days=4)))
    assert len(signals(db)) == 4  # worsened past the step: both sleeves fire again

    rules_job(make_ctx(settings, [], now=NOW + timedelta(days=12)))
    assert len(signals(db)) == 6  # the cooldown from day 4 is over


def test_a_cleared_condition_fires_again_at_once_when_it_returns(
    settings: Settings, db, book
) -> None:  # type: ignore[no-untyped-def]
    strategy(db, "Core", "active")
    buy(db, book["account"], book["equity"], 10, date(2024, 3, 1))
    db.commit()
    rules_job(make_ctx(settings, [], now=NOW))
    buy(db, book["account"], book["gold"], 10, date(2024, 3, 2))  # balanced again
    db.commit()
    rules_job(make_ctx(settings, [], now=NOW + timedelta(hours=1)))
    buy(db, book["account"], book["equity"], 10, date(2024, 3, 3))  # and out again
    db.commit()
    rules_job(make_ctx(settings, [], now=NOW + timedelta(hours=2)))
    assert len(signals(db)) == 4


def test_shadow_strategies_log_signals_that_are_marked_as_such(
    settings: Settings, db, book, client: TestClient, owner: None
) -> None:  # type: ignore[no-untyped-def]
    strategy(db, "Core", "off")
    shadow_id = strategy(db, "Challenger", "shadow")
    buy(db, book["account"], book["equity"], 10, date(2024, 3, 1))
    db.commit()
    rules_job(make_ctx(settings, [], now=NOW))
    fired = signals(db)
    assert fired and all(s.shadow for s in fired)  # nothing from the strategy that is off

    client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    listed = client.get("/api/v1/strategies/signals", params={"shadow": True}).json()
    assert {s["strategy_name"] for s in listed} == {"Challenger"}
    assert client.get("/api/v1/strategies/signals", params={"shadow": False}).json() == []
    status = client.get(f"/api/v1/strategies/{shadow_id}/status").json()
    assert status["rules"] == [
        {"rule_id": "drift", "rule_type": "drift_band", "ready": True, "reason": None}
    ]
    assert {s["id"] for s in status["sleeves"]} == {"equity", "gold"}


def test_run_now_queues_one_check(db, client: TestClient, owner: None) -> None:  # type: ignore[no-untyped-def]
    client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    assert client.post("/api/v1/strategies/run").status_code == 202
    assert client.post("/api/v1/strategies/run").status_code == 202
    pending = db.scalars(select(JobRequest).where(JobRequest.job == "rules")).all()
    assert len(pending) == 1


def test_without_a_strategy_the_job_says_so(settings: Settings) -> None:
    result = rules_job(make_ctx(settings, [], now=NOW))
    assert result.status == "ok" and "No active or shadow strategy" in result.log
