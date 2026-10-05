# ruff: noqa: F811  (the fixtures are imported from test_portfolio and used as parameters)
"""Returns, allocation, risk, attribution, benchmarks and the simulator, on the book of
tests/integration/test_portfolio.py (fund F on Xetra, closes 100 on 2 Jan rising by one a trading day):

    2 Jan  buy 10 @ 100, fee 1   -> 1001 in
    8 Jan  buy  5 @ 104          -> 520 in
    10 Jan dividend 3
    11 Jan sell  4 @ 106, fee 1  -> 423 out
    12 Jan close 108, 11 units = 1188; net contributions 1098; total result 93
"""

from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from folio.analytics_service import clear_cache
from folio.db.models_ledger import LedgerTransaction, PriceBar
from tests.integration.test_portfolio import api, book, db, tx  # noqa: F401
from tests.marketdata_helpers import make_listing

D = Decimal
PARAMS = {"as_of": "2024-01-15"}


@pytest.fixture(autouse=True)
def fresh_cache() -> None:
    clear_cache()


def get(api: TestClient, path: str, **params: Any) -> Any:
    r = api.get(f"/api/v1/portfolio/{path}", params={**PARAMS, **params})
    assert r.status_code == 200, r.text
    return r.json()


def second_instrument(db, closes: dict[str, str], **kw: Any):  # type: ignore[no-untyped-def]
    instrument, listing = make_listing(db, ticker="B", isin=None, **kw)
    for day, close in closes.items():
        db.add(
            PriceBar(
                listing_id=listing.id, date=date.fromisoformat(day), close=D(close), source="x"
            )
        )
    db.commit()
    return instrument


def xirr_by_bisection(flows: list[tuple[date, float]]) -> float:
    """An independent solver, to compare the production one against."""
    t0 = flows[0][0]

    def npv(rate: float) -> float:
        return sum(cf / (1 + rate) ** ((d - t0).days / 365) for d, cf in flows)

    lo, hi = -0.99, 50.0
    for _ in range(400):
        mid = (lo + hi) / 2
        if (npv(mid) > 0) == (npv(lo) > 0):
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# --- returns ------------------------------------------------------------------------------------


def test_portfolio_returns_match_a_hand_computation(api, book) -> None:  # type: ignore[no-untyped-def]
    r = get(api, "returns", period="MAX")
    expected = Fraction(1030, 1001) * Fraction(1593, 1550) * Fraction(1188, 1167) - 1
    assert abs(D(r["twr"]) - D(expected.numerator) / D(expected.denominator)) < D("1E-20")
    assert (r["start"], r["end"]) == ("2024-01-01", "2024-01-15")  # the day before the first buy
    # the result: 1188 now, 1098 net put in, 3 income
    assert D(r["pnl_eur"]) == 93 and D(r["value_end_eur"]) == 1188 and D(r["net_flows_eur"]) == 1098
    flows = [
        (date(2024, 1, 2), -1001.0),
        (date(2024, 1, 8), -520.0),
        (date(2024, 1, 10), 3.0),
        (date(2024, 1, 11), 423.0),
        (date(2024, 1, 15), 1188.0),
    ]
    assert abs(float(r["xirr"]) - xirr_by_bisection(flows)) < 1e-6


def test_a_sleeve_an_instrument_and_an_account_scope_agree_for_a_single_holding(api, book) -> None:  # type: ignore[no-untyped-def]
    sleeve = api.post("/api/v1/sleeves", json={"name": "core"}).json()
    api.patch(f"/api/v1/instruments/{book['fund']}", json={"sleeve_id": sleeve["id"]})
    whole = get(api, "returns", period="MAX")
    for scope in (
        f"instrument:{book['fund']}",
        f"sleeve:{sleeve['id']}",
        f"account:{book['account']}",
    ):
        part = get(api, "returns", period="MAX", scope=scope)
        assert D(part["twr"]) == D(whole["twr"]) and D(part["pnl_eur"]) == D(whole["pnl_eur"])


def test_returns_for_a_period_and_the_annualised_form(api, book) -> None:  # type: ignore[no-untyped-def]
    r = get(api, "returns", period="CUSTOM", **{"from": "2024-01-11", "to": "2024-01-12"})
    # one day: 1177 -> 1188 with nothing moving in
    assert abs(D(r["twr"]) - (D(1188) / D(1177) - 1)) < D("1E-25")
    assert D(r["pnl_eur"]) == 11 and D(r["net_flows_eur"]) == 0
    assert r["twr_annualised"] is not None and D(r["twr_annualised"]) > D(r["twr"])


def test_returns_input_errors_are_explained(api, book) -> None:  # type: ignore[no-untyped-def]
    bad = api.get("/api/v1/portfolio/returns", params={**PARAMS, "scope": "everything"})
    assert bad.status_code == 422 and "sleeve:ID" in bad.json()["detail"]
    period = api.get("/api/v1/portfolio/returns", params={**PARAMS, "period": "7Y"})
    assert period.status_code == 422
    nothing = api.get("/api/v1/portfolio/returns", params={"as_of": "2023-01-01"})
    assert nothing.status_code == 404 and "nothing to measure" in nothing.json()["detail"]
    assert (
        api.get("/api/v1/portfolio/returns", params={**PARAMS, "account": 999}).status_code == 404
    )


def test_every_position_gets_its_own_return(api, book) -> None:  # type: ignore[no-untyped-def]
    rows = get(api, "returns/instruments", period="MAX")
    assert [r["instrument_id"] for r in rows] == [book["fund"]]
    assert D(rows[0]["pnl_eur"]) == 93 and D(rows[0]["value_end_eur"]) == 1188


# --- allocation and drift -----------------------------------------------------------------------


def test_allocation_by_group_with_drift_against_sleeve_targets(api, book) -> None:  # type: ignore[no-untyped-def]
    core = api.post(
        "/api/v1/sleeves", json={"name": "core", "target_pct": "60", "band_pct": "5"}
    ).json()
    api.post("/api/v1/sleeves", json={"name": "gold", "target_pct": "40"})
    api.patch(f"/api/v1/instruments/{book['fund']}", json={"sleeve_id": core["id"], "region": "US"})
    by_class = get(api, "allocation", group_by="asset_class")
    assert [(s["key"], D(s["weight"])) for s in by_class["slices"]] == [("ETF", D(1))]
    assert by_class["slices"][0]["target"] is None and D(by_class["total_eur"]) == 1188

    sleeves = {s["key"]: s for s in get(api, "allocation", group_by="sleeve")["slices"]}
    assert D(sleeves["core"]["drift_pp"]) == D("0.4")  # 100% held against a 60% target
    assert sleeves["core"]["outside_band"] is True
    assert D(sleeves["gold"]["weight"]) == 0 and D(sleeves["gold"]["drift_pp"]) == D("-0.4")
    assert sleeves["gold"]["outside_band"] is None  # no band set
    assert get(api, "allocation", group_by="region")["slices"][0]["key"] == "US"
    assert get(api, "allocation", group_by="sector")["slices"][0]["key"] == "Unclassified"
    assert get(api, "allocation", group_by="currency")["slices"][0]["key"] == "EUR"
    assert get(api, "allocation", group_by="instrument")["slices"][0]["key"] == "F fund"


def test_the_drift_the_api_reports_is_the_domain_functions_drift(api, book) -> None:  # type: ignore[no-untyped-def]
    from folio.analytics.allocation import drift

    core = api.post(
        "/api/v1/sleeves", json={"name": "core", "target_pct": "70", "band_pct": "10"}
    ).json()
    api.patch(f"/api/v1/instruments/{book['fund']}", json={"sleeve_id": core["id"]})
    other = second_instrument(book_db(api), {"2024-01-02": "50", "2024-01-12": "50"})
    del other
    s = {x["key"]: x for x in get(api, "allocation", group_by="sleeve")["slices"]}["core"]
    expected = drift(D(s["weight"]), D("0.7"), D("0.1"))
    assert expected is not None
    assert D(s["drift_pp"]) == expected.pp
    assert abs(D(s["drift_relative"]) - expected.relative) < D("1E-25")  # type: ignore[operator]
    assert s["outside_band"] == expected.outside_band


def book_db(api):  # type: ignore[no-untyped-def]
    from folio.db.engine import make_engine, make_session_factory

    return make_session_factory(make_engine(api.app.state.settings.db_url))()  # type: ignore[attr-defined]


def test_the_cache_follows_the_data(api, book, db) -> None:  # type: ignore[no-untyped-def]
    before = D(get(api, "allocation")["total_eur"])
    assert before == 1188
    tx(api, account_id=book["account"], instrument_id=book["fund"], type="buy",
       trade_date="2024-01-12", quantity="2", price="108")  # fmt: skip
    assert D(get(api, "allocation")["total_eur"]) == 1188 + 216  # not the cached figure
    again = get(api, "allocation")
    assert D(again["total_eur"]) == 1404


# --- risk ---------------------------------------------------------------------------------------


def test_risk_figures_and_the_correlation_matrix(api, book) -> None:  # type: ignore[no-untyped-def]
    r = get(api, "risk", window="MAX")
    assert D(r["volatility"]) > 0 and D(r["max_drawdown"]) <= 0
    assert D(r["current_drawdown"]) == 0 and r["benchmark_id"] is None
    assert D(r["risk_free"]) == D("0.02")  # the fixed fallback until the ECB series is stored
    assert r["sharpe"] is not None
    assert len(r["drawdown"]) >= 9
    matrix = {m["window"]: m for m in r["correlations"]}
    assert matrix["1Y"]["instruments"] == [book["fund"]] and D(matrix["1Y"]["values"][0][0]) == 1


def test_beta_against_a_benchmark(api, book, db) -> None:  # type: ignore[no-untyped-def]
    bench = second_instrument(
        db,
        {f"2024-01-{d:02d}": str(50 + i) for i, d in enumerate([2, 3, 4, 5, 8, 9, 10, 11, 12])},
    )
    r = get(api, "risk", window="MAX", benchmark=bench.id)
    assert r["benchmark_id"] == bench.id and r["beta"] is not None
    assert D(0) < D(r["beta"]) < D(3)  # the exact figure is pinned in the unit tests


def test_risk_without_data_says_so(api) -> None:  # type: ignore[no-untyped-def]
    r = api.get("/api/v1/portfolio/risk", params=PARAMS)
    assert r.status_code == 404 and "no transactions" in r.json()["detail"]


# --- attribution --------------------------------------------------------------------------------


def test_contributions_add_up_to_the_portfolio_result(api, book) -> None:  # type: ignore[no-untyped-def]
    tx(api, account_id=book["account"], type="fee", trade_date="2024-01-12", net_amount_eur="2.5")
    r = get(api, "attribution", period="MAX")
    by_key = {c["key"]: c for c in r["contributions"]}
    assert D(by_key[str(book["fund"])]["pnl_eur"]) == 93
    assert D(by_key["other"]["pnl_eur"]) == D("-2.5") and "costs" in by_key["other"]["name"]
    assert D(r["portfolio_pnl_eur"]) == D("90.5")
    assert sum(D(c["pnl_eur"]) for c in r["contributions"]) == D("90.5")
    assert abs(sum(D(c["points"]) for c in r["contributions"]) - D(r["total_return"])) < D("1E-20")


def test_attribution_of_an_empty_period_is_explained(api, book) -> None:  # type: ignore[no-untyped-def]
    r = api.get(
        "/api/v1/portfolio/attribution",
        params={**PARAMS, "period": "CUSTOM", "from": "2024-01-12", "to": "2024-01-12"},
    )
    assert r.status_code == 404


# --- benchmarks ---------------------------------------------------------------------------------


def test_the_portfolio_and_benchmarks_are_rebased_to_100(api, book, db) -> None:  # type: ignore[no-untyped-def]
    bench = second_instrument(db, {"2024-01-02": "50", "2024-01-05": "55", "2024-01-12": "60"})
    api.patch(f"/api/v1/instruments/{bench.id}", json={"is_benchmark": True})
    r = get(api, "benchmarks", period="MAX")
    series = {s["key"]: s for s in r["series"]}
    assert series["portfolio"]["label"] == "Portfolio"
    assert D(series["portfolio"]["points"][0]["value"]) == 100
    b = series[str(bench.id)]
    assert (b["points"][0]["date"], D(b["points"][0]["value"])) == ("2024-01-02", D(100))
    assert D(b["points"][-1]["value"]) == D(60) / D(50) * 100  # the last close over the first
    explicit = get(api, "benchmarks", period="MAX", ids=[bench.id])
    assert [s["key"] for s in explicit["series"]] == ["portfolio", str(bench.id)]


def test_at_most_three_benchmarks(api, book) -> None:  # type: ignore[no-untyped-def]
    r = api.get("/api/v1/portfolio/benchmarks", params={**PARAMS, "ids": [1, 2, 3, 4]})
    assert r.status_code == 422 and "at most three" in r.json()["detail"]


# --- the simulator ------------------------------------------------------------------------------


def ledger_rows(db) -> int:  # type: ignore[no-untyped-def]
    db.expire_all()
    return db.scalar(select(func.count()).select_from(LedgerTransaction)) or 0


def test_a_simulated_purchase_shifts_the_allocation_and_needs_cash(api, book, db) -> None:  # type: ignore[no-untyped-def]
    other = second_instrument(db, {"2024-01-02": "50", "2024-01-12": "50"})
    rows_before = ledger_rows(db)
    r = api.post(
        "/api/v1/portfolio/simulate",
        json={
            "as_of": "2024-01-15",
            "group_by": "instrument",
            "trades": [
                {"instrument_id": other.id, "side": "buy", "quantity": "20"},
                {"instrument_id": book["fund"], "side": "sell", "quantity": "1", "fees_eur": "1"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    # 20 x 50 bought, 1 x 108 sold, 1 fee: 1000 - 108 + 1 to find
    assert D(out["cash_needed_eur"]) == D("893")
    before = {s["key"]: D(s["value_eur"]) for s in out["before"]["slices"]}
    after = {s["key"]: D(s["value_eur"]) for s in out["after"]["slices"]}
    assert before == {"F fund": D(1188)}
    assert after == {"F fund": D(1080), "B fund": D(1000)}
    assert abs(D(out["after"]["slices"][0]["weight"]) - D(1080) / D(2080)) < D("1E-25")
    moved = {p["name"]: (D(p["quantity_before"]), D(p["quantity_after"])) for p in out["positions"]}
    assert moved["F fund"] == (D(11), D(10)) and moved["B fund"] == (D(0), D(20))
    # nothing was written
    assert ledger_rows(db) == rows_before
    assert api.get("/api/v1/transactions", params={"limit": 50}).json()["next_cursor"] is None
    assert D(get(api, "allocation")["total_eur"]) == 1188


def test_a_simulated_sale_of_more_than_is_held_is_refused_in_plain_words(api, book) -> None:  # type: ignore[no-untyped-def]
    r = api.post(
        "/api/v1/portfolio/simulate",
        json={
            "as_of": "2024-01-15",
            "trades": [{"instrument_id": book["fund"], "side": "sell", "quantity": "50"}],
        },
    )
    assert r.status_code == 422
    assert "You hold 11" in r.json()["detail"] and "needs 50" in r.json()["detail"]


def test_an_unpriced_instrument_needs_a_price_to_assume(api, book, db) -> None:  # type: ignore[no-untyped-def]
    unpriced = second_instrument(db, {})
    body = {
        "as_of": "2024-01-15",
        "trades": [{"instrument_id": unpriced.id, "side": "buy", "quantity": "5"}],
    }
    r = api.post("/api/v1/portfolio/simulate", json=body)
    assert r.status_code == 422 and "no price" in r.json()["detail"]
    body["trades"][0]["price_eur"] = "20"  # type: ignore[index]
    ok = api.post("/api/v1/portfolio/simulate", json=body)
    assert ok.status_code == 200 and D(ok.json()["cash_needed_eur"]) == 100


def test_the_simulator_rejects_unknown_instruments_and_empty_trade_lists(api, book) -> None:  # type: ignore[no-untyped-def]
    unknown = api.post(
        "/api/v1/portfolio/simulate",
        json={"trades": [{"instrument_id": 999, "side": "buy", "quantity": "1"}]},
    )
    assert unknown.status_code == 404
    assert api.post("/api/v1/portfolio/simulate", json={"trades": []}).status_code == 422


def test_requires_login(client: TestClient) -> None:
    for path in ("returns", "allocation", "risk", "attribution", "benchmarks", "history"):
        assert client.get(f"/api/v1/portfolio/{path}").status_code == 401
    assert client.post("/api/v1/portfolio/simulate", json={"trades": []}).status_code == 401
