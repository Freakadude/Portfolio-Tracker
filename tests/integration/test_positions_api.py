"""Positions and position detail (FR-TX-05). Every number below is computed by hand."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models_ledger import FxRate, PriceBar
from folio.domain.ledger import precise
from tests.conftest import PASSWORD, USERNAME
from tests.marketdata_helpers import make_listing

D = Decimal
VALUATION = "2024-04-10"


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


@pytest.fixture
def api(client: TestClient, owner: None) -> TestClient:
    client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return client


def post(api: TestClient, **body: Any) -> dict[str, Any]:
    r = api.post("/api/v1/transactions", json=body)
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def add_bars(db, listing_id: int, bars: dict[str, str]) -> None:  # type: ignore[no-untyped-def]
    for day, close in bars.items():
        db.add(
            PriceBar(
                listing_id=listing_id, date=date.fromisoformat(day), close=D(close), source="yahoo"
            )
        )
    db.commit()


@pytest.fixture
def book(api: TestClient, db) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """One account with three holdings:

    SXR8 (EUR): the golden FIFO scenario. Buys 10 @ 100 (+1 fee) and 10 @ 120 (+1 fee), sells 15
      @ 130 (-2 fee). 5 units remain with a cost of 600.5; realized 346.5.
    AAA (USD): 10 @ 50 USD at the owner's rate 0.9 plus 1 EUR fee, cost 451.
    BBB (EUR): 1 @ 10 with no price at all.
    """
    account = api.post("/api/v1/accounts", json={"name": "Degiro"}).json()
    sxr8, sxr8_listing = make_listing(db, ticker="SXR8")
    aaa, aaa_listing = make_listing(db, ticker="AAA", currency="USD", isin="IE0000000001")
    bbb, _ = make_listing(db, ticker="BBB", isin="IE0000000002")
    db.add_all(
        [
            FxRate(date=date(2024, 4, 9), currency="USD", rate_per_eur=D("1.25")),
            FxRate(date=date(2024, 4, 10), currency="USD", rate_per_eur=D("1.25")),
        ]
    )
    db.commit()
    add_bars(db, sxr8_listing.id, {"2024-02-14": "125", "2024-04-09": "138", "2024-04-10": "140"})
    add_bars(db, aaa_listing.id, {"2024-04-09": "58", "2024-04-10": "60"})
    a = account["id"]
    for day, qty, price in (("2024-01-02", "10", "100"), ("2024-02-01", "10", "120")):
        post(api, account_id=a, instrument_id=sxr8.id, type="buy", trade_date=day,
             quantity=qty, price=price, fees="1")  # fmt: skip
    post(api, account_id=a, instrument_id=sxr8.id, type="sell", trade_date="2024-03-01",
         quantity="15", price="130", fees="2")  # fmt: skip
    post(api, account_id=a, instrument_id=aaa.id, type="buy", trade_date="2024-03-15",
         quantity="10", price="50", fx_rate_to_eur="0.9", fees="1")  # fmt: skip
    post(api, account_id=a, instrument_id=bbb.id, type="buy", trade_date="2024-03-20",
         quantity="1", price="10")  # fmt: skip
    return {"account": a, "sxr8": sxr8.id, "aaa": aaa.id, "bbb": bbb.id}


def by_ticker(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {p["ticker"]: p for p in body["positions"]}


def close(a: str | None, b: Decimal, tolerance: str = "1E-12") -> bool:
    return a is not None and abs(Decimal(a) - b) < D(tolerance)


def test_requires_login(client: TestClient) -> None:
    assert client.get("/api/v1/positions").status_code == 401
    assert client.get("/api/v1/positions/1").status_code == 401


@pytest.mark.parametrize(
    "as_of", [None, VALUATION], ids=["from derived tables", "replayed to a date"]
)
def test_position_metrics_match_a_hand_computation(
    api: TestClient, book: dict[str, Any], as_of: str | None
) -> None:
    url = "/api/v1/positions" + (f"?as_of={as_of}" if as_of else "")
    body = api.get(url).json()
    rows = by_ticker(body)
    assert set(rows) == {"SXR8", "AAA", "BBB"}

    sxr8 = rows["SXR8"]  # 5 units, cost 600.5, price 140 (previous close 138)
    assert (sxr8["account_name"], sxr8["name"], sxr8["currency"]) == ("Degiro", "SXR8 fund", "EUR")
    assert Decimal(sxr8["quantity"]) == 5 and Decimal(sxr8["cost_basis_eur"]) == D("600.5")
    assert Decimal(sxr8["avg_cost_eur"]) == D("120.1")
    assert Decimal(sxr8["market_value_eur"]) == 700 and Decimal(sxr8["unrealized_pnl_eur"]) == D(
        "99.5"
    )
    assert close(sxr8["unrealized_ratio"], D("99.5") / D("600.5"))
    assert Decimal(sxr8["realized_pnl_eur"]) == D("346.5") and Decimal(sxr8["income_eur"]) == 0
    assert Decimal(sxr8["total_return_eur"]) == 446  # 99.5 unrealized + 346.5 realized
    assert close(sxr8["total_return_ratio"], D(446) / D(2202))  # over the 2202 ever invested
    assert Decimal(sxr8["day_change_eur"]) == 10 and close(sxr8["day_change_ratio"], D(10) / D(690))
    assert sxr8["first_trade_date"] == "2024-01-02"
    assert (sxr8["price"]["date"], Decimal(sxr8["price"]["close"]), Decimal(sxr8["price"]["previous_close"])) == (
        "2024-04-10", D(140), D(138),
    )  # fmt: skip

    aaa = rows["AAA"]  # 10 units, 600 USD at 0.8 EUR/USD = 480; cost 451
    assert Decimal(aaa["cost_basis_eur"]) == 451 and Decimal(aaa["market_value_eur"]) == 480
    assert Decimal(aaa["unrealized_pnl_eur"]) == 29 and Decimal(aaa["day_change_eur"]) == 16
    # the same position in the trading currency, so price moves and currency moves separate
    assert Decimal(aaa["market_value_native"]) == 600 and Decimal(aaa["cost_basis_native"]) == 500
    assert Decimal(aaa["unrealized_pnl_native"]) == 100

    bbb = rows["BBB"]  # never priced: shown, but nothing is guessed
    assert Decimal(bbb["cost_basis_eur"]) == 10 and bbb["market_value_eur"] is None
    assert bbb["unrealized_pnl_eur"] is None and bbb["weight"] is None and bbb["price"] is None
    assert bbb["note"] == "No price yet."

    totals = body["totals"]
    assert totals["positions"] == 3 and totals["unvalued_positions"] == 1
    assert Decimal(totals["market_value_eur"]) == 1180 and Decimal(totals["cost_basis_eur"]) == D(
        "1061.5"
    )
    assert Decimal(totals["unrealized_pnl_eur"]) == D("128.5") and Decimal(
        totals["realized_pnl_eur"]
    ) == D("346.5")
    assert totals["day_change_eur"] is None  # one holding has no price, so the total is unknown
    with precise():
        assert close(totals["unrealized_ratio"], D("128.5") / D("1051.5"))  # over the valued cost
        assert close(sxr8["weight"], D(700) / D(1180)) and close(aaa["weight"], D(480) / D(1180))


def test_valuing_at_an_earlier_date_replays_the_ledger(
    api: TestClient, book: dict[str, Any]
) -> None:
    # 15 February: only the two buys have happened and the latest close is 125 (14 February)
    rows = by_ticker(api.get("/api/v1/positions?as_of=2024-02-15").json())
    assert set(rows) == {"SXR8"}
    sxr8 = rows["SXR8"]
    assert Decimal(sxr8["quantity"]) == 20 and Decimal(sxr8["cost_basis_eur"]) == 2202
    assert Decimal(sxr8["market_value_eur"]) == 2500 and Decimal(sxr8["unrealized_pnl_eur"]) == 298
    assert Decimal(sxr8["realized_pnl_eur"]) == 0
    assert (
        sxr8["price"]["date"] == "2024-02-14" and sxr8["day_change_eur"] is None
    )  # no earlier bar


def test_closed_positions_are_hidden_unless_asked_for(
    api: TestClient, book: dict[str, Any], db
) -> None:  # type: ignore[no-untyped-def]
    post(api, account_id=book["account"], instrument_id=book["bbb"], type="sell", trade_date="2024-03-25",
         quantity="1", price="12")  # fmt: skip
    assert "BBB" not in by_ticker(api.get("/api/v1/positions").json())
    closed = by_ticker(api.get("/api/v1/positions?include_closed=true").json())["BBB"]
    assert Decimal(closed["quantity"]) == 0 and Decimal(closed["realized_pnl_eur"]) == 2
    assert closed["avg_cost_eur"] is None


def test_account_filter_keeps_portfolio_wide_weights(
    api: TestClient, book: dict[str, Any], db
) -> None:  # type: ignore[no-untyped-def]
    other = api.post("/api/v1/accounts", json={"name": "Other"}).json()["id"]
    post(api, account_id=other, instrument_id=book["aaa"], type="buy", trade_date="2024-03-16",
         quantity="10", price="50", fx_rate_to_eur="0.9", fees="1")  # fmt: skip
    only_other = api.get(f"/api/v1/positions?account={other}").json()
    assert [p["ticker"] for p in only_other["positions"]] == ["AAA"]
    assert only_other["totals"]["positions"] == 1
    with precise():
        # the weight is against the whole portfolio (700 + 480 + 480), not just this account
        assert close(only_other["positions"][0]["weight"], D(480) / D(1660))


def test_a_stale_price_is_flagged_but_still_used(api: TestClient, book: dict[str, Any]) -> None:
    rows = by_ticker(api.get("/api/v1/positions").json())  # "today" is long after April 2024
    assert rows["SXR8"]["price"]["stale"] is True
    assert Decimal(rows["SXR8"]["market_value_eur"]) == 700


def test_a_missing_ecb_rate_leaves_the_market_value_empty_with_an_explanation(
    api: TestClient, book: dict[str, Any], db
) -> None:  # type: ignore[no-untyped-def]
    db.query(FxRate).delete()
    db.commit()
    aaa = by_ticker(api.get("/api/v1/positions").json())["AAA"]
    assert aaa["market_value_eur"] is None and "No ECB rate for USD" in aaa["note"]


def test_position_detail_lists_lots_matches_and_history(
    api: TestClient, book: dict[str, Any]
) -> None:
    r = api.get(f"/api/v1/positions/{book['sxr8']}?as_of={VALUATION}")
    assert r.status_code == 200
    d = r.json()
    assert d["instrument"]["ticker"] == "SXR8" and d["instrument"]["isin"] == "IE00B5BMR087"
    assert d["instrument"]["product_url"] is None  # the owner has not saved the issuer's page
    saved = api.patch(
        f"/api/v1/instruments/{book['sxr8']}", json={"product_url": "https://example.org/fund"}
    )
    assert saved.status_code == 200
    again = api.get(f"/api/v1/positions/{book['sxr8']}?as_of={VALUATION}").json()
    assert again["instrument"]["product_url"] == "https://example.org/fund"
    s = d["summary"]
    assert Decimal(s["quantity"]) == 5 and Decimal(s["market_value_eur"]) == 700

    (lot,) = d["lots"]  # FIFO: the first lot is used up, 5 units of the second remain
    assert (lot["trade_date"], Decimal(lot["open_quantity"]), Decimal(lot["cost_eur"])) == (
        "2024-02-01",
        5,
        D("600.5"),
    )
    assert Decimal(lot["avg_cost_eur"]) == D("120.1")
    assert Decimal(lot["market_value_eur"]) == 700 and Decimal(lot["unrealized_pnl_eur"]) == D(
        "99.5"
    )

    assert [(m["quantity"], Decimal(m["cost_eur"]), m["sell_date"]) for m in d["matches"]] == [
        ("10", D("1001"), "2024-03-01"), ("5", D("600.5"), "2024-03-01"),
    ]  # fmt: skip
    assert [(t["type"], t["trade_date"]) for t in d["transactions"]] == [
        ("sell", "2024-03-01"),
        ("buy", "2024-02-01"),
        ("buy", "2024-01-02"),
    ]  # newest first, ready for the page's history table


def test_position_detail_figures_reconcile(api: TestClient, book: dict[str, Any]) -> None:
    """The invariants of section 5, checked from API data alone."""
    d = api.get(f"/api/v1/positions/{book['sxr8']}?as_of={VALUATION}").json()
    s = d["summary"]
    with precise():
        open_cost = sum((Decimal(lot["cost_eur"]) for lot in d["lots"]), D(0))
        open_qty = sum((Decimal(lot["open_quantity"]) for lot in d["lots"]), D(0))
        matched_cost = sum((Decimal(m["cost_eur"]) for m in d["matches"]), D(0))
        proceeds = sum((Decimal(m["proceeds_eur"]) for m in d["matches"]), D(0))
        buys = [t for t in d["transactions"] if t["type"] == "buy"]
        invested = sum(
            (Decimal(t["quantity"]) * Decimal(t["price"]) + Decimal(t["fees"]) for t in buys), D(0)
        )
        realized = Decimal(s["realized_pnl_eur"])
        # 1: lot quantities sum to the position quantity
        assert open_qty == Decimal(s["quantity"])
        # open cost is the cost basis; realized P&L is explained by the matches
        assert open_cost == Decimal(s["cost_basis_eur"])
        assert proceeds - matched_cost == realized
        # nothing is lost between buying and selling: open cost + consumed cost = everything bought
        assert open_cost + matched_cost == invested
        # 2: realized + unrealized = market value + net sale proceeds - total purchase cost
        assert (
            realized + Decimal(s["unrealized_pnl_eur"])
            == Decimal(s["market_value_eur"]) + proceeds - invested
        )


def test_position_detail_aggregates_accounts_unless_one_is_chosen(
    api: TestClient, book: dict[str, Any]
) -> None:
    other = api.post("/api/v1/accounts", json={"name": "Other"}).json()["id"]
    post(api, account_id=other, instrument_id=book["sxr8"], type="buy", trade_date="2024-03-02",
         quantity="4", price="130")  # fmt: skip
    both = api.get(f"/api/v1/positions/{book['sxr8']}?as_of={VALUATION}").json()
    assert Decimal(both["summary"]["quantity"]) == 9 and Decimal(
        both["summary"]["cost_basis_eur"]
    ) == D("1120.5")
    assert {lot["account_id"] for lot in both["lots"]} == {book["account"], other}
    only = api.get(f"/api/v1/positions/{book['sxr8']}?account={other}&as_of={VALUATION}").json()
    assert Decimal(only["summary"]["quantity"]) == 4 and len(only["lots"]) == 1
    assert [t["account_id"] for t in only["transactions"]] == [other]


def test_detail_for_an_instrument_without_a_position_and_unknown_ones(api: TestClient, db) -> None:  # type: ignore[no-untyped-def]
    instrument, listing = make_listing(db, ticker="NEW", isin="IE0000000009")
    add_bars(db, listing.id, {"2024-04-10": "10"})
    d = api.get(f"/api/v1/positions/{instrument.id}?as_of={VALUATION}")
    assert d.status_code == 200
    body = d.json()
    assert body["lots"] == [] and body["matches"] == [] and body["transactions"] == []
    assert Decimal(body["summary"]["quantity"]) == 0 and body["summary"]["price"]["close"] == "10"
    assert api.get("/api/v1/positions/999").status_code == 404


def test_detail_before_the_first_buy_shows_nothing_held(
    api: TestClient, book: dict[str, Any]
) -> None:
    d = api.get(f"/api/v1/positions/{book['sxr8']}?as_of=2023-12-31").json()
    assert Decimal(d["summary"]["quantity"]) == 0 and d["lots"] == [] and d["transactions"] == []
