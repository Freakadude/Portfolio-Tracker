"""Calculators on real holdings through the API, and orders copied into drafts (FR-ST-05)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import Account
from folio.db.models_ledger import LedgerTransaction, PriceBar
from folio.ledger_service import TransactionIn, create_transaction
from tests.conftest import PASSWORD, USERNAME
from tests.marketdata_helpers import make_listing

D = Decimal
YAML = """\
strategy:
  name: Core
  sleeves:
    - { id: equity, members: [IE00B5BMR087], target_pct: 50, soft_band_pp: 5, trim_threshold_pct: 60 }
    - { id: gold, members: [IE00B4ND3602], target_pct: 30, soft_band_pp: 5 }
    - { id: bonds, members: [IE00B3F81R35], target_pct: 20, soft_band_pp: 5 }
  contribution_plan: { amount_eur: 1000, cadence: monthly, min_order_eur: 100 }
"""


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


@pytest.fixture
def api(client: TestClient, owner: None) -> TestClient:
    client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return client


@pytest.fixture
def book(db: Session) -> dict[str, int]:
    """Equity 14 x 50 = 700, gold 6 x 50 = 300, bonds not held yet (priced at 25)."""
    ids = {}
    today = date.today()
    for name, isin, price in (
        ("equity", "IE00B5BMR087", 50),
        ("gold", "IE00B4ND3602", 50),
        ("bonds", "IE00B3F81R35", 25),
    ):
        instrument, listing = make_listing(db, ticker=name.upper(), isin=isin)
        for back in range(10):
            db.add(
                PriceBar(
                    listing_id=listing.id,
                    date=today - timedelta(days=back),
                    close=D(price),
                    source="t",
                )
            )
        ids[name] = instrument.id
    account = Account(name="Broker")
    db.add(account)
    db.flush()
    for name, units in (("equity", 14), ("gold", 6)):
        create_transaction(db, TransactionIn(account_id=account.id, type="buy", trade_date=today - timedelta(days=5),
                                             instrument_id=ids[name], quantity=D(units), price=D(50)))  # fmt: skip
    db.commit()
    ids["account"] = account.id
    return ids


def strategy(api: TestClient) -> int:
    return int(api.post("/api/v1/strategies", json={"yaml": YAML}).json()["id"])


def test_the_allocator_sends_new_money_to_the_shortfalls_and_adds_up_exactly(
    api: TestClient, book
) -> None:  # type: ignore[no-untyped-def]
    sid = strategy(api)
    plan = api.post(f"/api/v1/strategies/{sid}/calculate", json={"kind": "allocator"}).json()
    # T + C = 2000: equity should be 1000 (300 short), gold 600 (300), bonds 400 (400)
    buys = {o["sleeve"]: (D(o["quantity"]), D(o["amount_eur"])) for o in plan["orders"]}
    assert buys == {"equity": (6, 300), "gold": (6, 300), "bonds": (16, 400)}
    total = sum((D(o["amount_eur"]) for o in plan["orders"]), D(0)) + D(plan["remainder_eur"])
    assert total == 1000  # the plan's amount, exactly
    assert (
        next(o for o in plan["orders"] if o["sleeve"] == "bonds")["instrument_id"] == book["bonds"]
    )
    assert D(plan["after"]["bonds"]) == D("0.2")


def test_trim_shows_the_realized_result_of_each_sale(api: TestClient, book) -> None:  # type: ignore[no-untyped-def]
    sid = strategy(api)
    plan = api.post(f"/api/v1/strategies/{sid}/calculate", json={"kind": "trim"}).json()
    # equity at 70% is above its 60% trim level: sell the 200 above its 50% target
    (sale,) = plan["orders"]
    assert (sale["side"], sale["sleeve"], D(sale["quantity"]), sale["account_id"]) == (
        "sell",
        "equity",
        4,
        book["account"],
    )
    assert D(sale["realized_pnl_eur"]) == 0  # bought and priced at 50
    missing = api.post(
        f"/api/v1/strategies/{sid}/calculate", json={"kind": "trim", "sleeve": "cash"}
    )
    assert missing.status_code == 404


def test_rebalance_with_new_money_prefers_buys(api: TestClient, book) -> None:  # type: ignore[no-untyped-def]
    sid = strategy(api)
    plan = api.post(
        f"/api/v1/strategies/{sid}/calculate", json={"kind": "rebalance", "amount_eur": "1000"}
    ).json()
    assert {o["side"] for o in plan["orders"]} == {"buy"}
    for sleeve, target in (("equity", "0.5"), ("gold", "0.3"), ("bonds", "0.2")):
        assert abs(D(plan["after"][sleeve]) - D(target)) <= D("0.05")


def test_orders_become_drafts_that_change_nothing_until_confirmed(
    api: TestClient, db, book
) -> None:  # type: ignore[no-untyped-def]
    sid = strategy(api)
    plan = api.post(f"/api/v1/strategies/{sid}/calculate", json={"kind": "allocator"}).json()
    orders = [
        {
            "side": o["side"],
            "instrument_id": o["instrument_id"],
            "quantity": o["quantity"],
            "price": o["price"],
        }
        for o in plan["orders"]
    ]
    r = api.post("/api/v1/strategies/orders/to-drafts", json={"orders": orders})
    assert r.status_code == 201, r.text
    ids = r.json()["transaction_ids"]
    drafts = db.scalars(select(LedgerTransaction).where(LedgerTransaction.id.in_(ids))).all()
    assert {(t.status, t.source, t.account_id) for t in drafts} == {
        ("draft", "strategy", book["account"])
    }
    positions = {
        p["name"]: D(p["quantity"]) for p in api.get("/api/v1/positions").json()["positions"]
    }
    assert positions == {"EQUITY fund": 14, "GOLD fund": 6}  # drafts change nothing

    confirmed = api.post(f"/api/v1/transactions/{ids[0]}/confirm", json={})
    assert confirmed.status_code == 200, confirmed.text
    bad = api.post(
        "/api/v1/strategies/orders/to-drafts", json={"orders": [{**orders[0], "quantity": "1.5"}]}
    )
    assert bad.status_code == 422 and "Whole units" in bad.json()["title"]
