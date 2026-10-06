"""Portfolio valuation, snapshots and the summary (FR-PF-01, FR-PF-10, FR-TX-06). Hand-computed.

The book used throughout (all in EUR, fund "F" traded on Xetra, closes 100 on 2 January 2024
and one more for each following trading day: 3 Jan 101, 4 Jan 102, 5 Jan 103, 8 Jan 104,
9 Jan 105, 10 Jan 106, 11 Jan 107, 12 Jan 108):

    2 Jan  buy 10 @ 100, fee 1        -> cost 1001, contributions 1001
    8 Jan  buy  5 @ 104               -> contributions 1521
    10 Jan dividend 3                 -> income 3
    11 Jan sell  4 @ 106, fee 1       -> net 423, contributions 1098
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from fractions import Fraction
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from folio.config import Settings
from folio.db.base import utcnow
from folio.db.engine import make_engine, make_session_factory
from folio.db.models_ledger import FxRate, JobRequest, JobRun, PortfolioSnapshot, PriceBar
from folio.jobs.portfolio import snapshots_job
from folio.portfolio import Valuation, lock_closed_years, save_snapshots
from tests.conftest import PASSWORD, USERNAME
from tests.marketdata_helpers import bars_for, make_ctx, make_listing

D = Decimal
AS_OF = "2024-01-12"


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


@pytest.fixture
def api(client: TestClient, owner: None) -> TestClient:
    client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return client


def tx(api: TestClient, **body: Any) -> dict[str, Any]:
    r = api.post("/api/v1/transactions", json=body)
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def add_bars(db, listing_id: int, rows: dict[str, str]) -> None:  # type: ignore[no-untyped-def]
    for day, close in rows.items():
        db.add(
            PriceBar(
                listing_id=listing_id, date=date.fromisoformat(day), close=D(close), source="x"
            )
        )
    db.commit()


@pytest.fixture
def book(api: TestClient, db) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    fund, listing = make_listing(db, ticker="F")
    for bar in bars_for("XETR", date(2024, 1, 1), date(2024, 1, 12)):
        db.add(PriceBar(listing_id=listing.id, date=bar.date, close=bar.close, source="x"))
    db.commit()
    account = api.post("/api/v1/accounts", json={"name": "Degiro"}).json()["id"]
    f, a = fund.id, account
    tx(
        api,
        account_id=a,
        instrument_id=f,
        type="buy",
        trade_date="2024-01-02",
        quantity="10",
        price="100",
        fees="1",
    )
    tx(
        api,
        account_id=a,
        instrument_id=f,
        type="buy",
        trade_date="2024-01-08",
        quantity="5",
        price="104",
    )
    tx(
        api,
        account_id=a,
        instrument_id=f,
        type="dividend",
        trade_date="2024-01-10",
        net_amount_eur="3",
    )
    tx(
        api,
        account_id=a,
        instrument_id=f,
        type="sell",
        trade_date="2024-01-11",
        quantity="4",
        price="106",
        fees="1",
    )
    return {"account": a, "fund": f, "listing": listing.id}


def point(db, day: str, **kw: Any):  # type: ignore[no-untyped-def]
    return Valuation.load(db, **kw).point(date.fromisoformat(day))


# --- valuing one day ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "value", "contributions", "income", "quantity"),
    [
        ("2024-01-02", 1000, 1001, 0, 10),  # 10 x 100
        ("2024-01-03", 1010, 1001, 0, 10),
        ("2024-01-06", 1030, 1001, 0, 10),  # a Saturday: Friday's close (103)
        ("2024-01-08", 1560, 1521, 0, 15),  # 15 x 104
        ("2024-01-10", 1590, 1521, 3, 15),  # 15 x 106, dividend received
        (
            "2024-01-11",
            1177,
            1098,
            3,
            11,
        ),  # sold 4: 11 x 107; contributions fall by the 423 received
        (
            "2024-01-20",
            1188,
            1098,
            3,
            11,
        ),  # after the last close (108 on 12 Jan): that close is used
    ],
)
def test_day_values_match_a_hand_computation(
    db, book, day: str, value: int, contributions: int, income: int, quantity: int
) -> None:  # type: ignore[no-untyped-def]
    p = point(db, day)
    assert (
        p.value_eur == value and p.net_contributions_eur == contributions and p.income_eur == income
    )
    assert p.total_pnl_eur == value - contributions + income
    (holding,) = p.holdings
    assert holding.quantity == quantity and p.unvalued == 0


def test_before_the_first_transaction_the_portfolio_is_empty(db, book) -> None:  # type: ignore[no-untyped-def]
    p = point(db, "2024-01-01")
    assert (p.value_eur, p.net_contributions_eur, p.holdings, p.unvalued) == (0, 0, (), 0)
    assert Valuation.load(db).first_date() == date(2024, 1, 2)


def test_a_holding_without_any_price_is_flagged_not_guessed(db, book, api: TestClient) -> None:  # type: ignore[no-untyped-def]
    unpriced, _ = make_listing(db, ticker="NOPRICE", isin="IE0000000001")
    db.commit()
    tx(
        api,
        account_id=book["account"],
        instrument_id=unpriced.id,
        type="buy",
        trade_date="2024-01-03",
        quantity="2",
        price="50",
    )
    p = point(db, "2024-01-05")
    assert p.unvalued == 1 and p.value_eur == 1030  # only the priced fund counts
    assert p.net_contributions_eur == 1101  # but the money put in still does
    missing = [h for h in p.holdings if h.value_eur is None]
    assert [h.instrument_id for h in missing] == [unpriced.id] and missing[0].price is None


def test_a_foreign_holding_uses_the_ecb_rate_of_the_price_date(db, api: TestClient) -> None:  # type: ignore[no-untyped-def]
    usd, listing = make_listing(db, ticker="U", currency="USD", isin="IE0000000002")
    add_bars(db, listing.id, {"2024-01-05": "50"})
    db.add(FxRate(date=date(2024, 1, 5), currency="USD", rate_per_eur=D("1.25")))
    db.commit()
    account = api.post("/api/v1/accounts", json={"name": "A"}).json()["id"]
    tx(
        api,
        account_id=account,
        instrument_id=usd.id,
        type="buy",
        trade_date="2024-01-03",
        quantity="10",
        price="48",
        fx_rate_to_eur="0.8",
    )
    assert point(db, "2024-01-05").value_eur == 400  # 10 x 50 USD x 0.8
    assert point(db, "2024-01-07").value_eur == 400  # a Sunday: Friday's close and Friday's rate
    db.query(FxRate).delete()
    db.commit()
    p = point(db, "2024-01-05")
    assert p.unvalued == 1 and p.value_eur == 0  # no rate, no value


def test_drafts_and_deleted_transactions_do_not_count(db, book, api: TestClient) -> None:  # type: ignore[no-untyped-def]
    extra = tx(
        api,
        account_id=book["account"],
        instrument_id=book["fund"],
        type="buy",
        trade_date="2024-01-09",
        quantity="100",
        price="105",
    )
    assert point(db, "2024-01-12").value_eur == 1188 + 100 * 108
    api.delete(f"/api/v1/transactions/{extra['id']}")
    assert point(db, "2024-01-12").value_eur == 1188


def test_valuation_can_be_limited_to_one_account(db, book, api: TestClient) -> None:  # type: ignore[no-untyped-def]
    other = api.post("/api/v1/accounts", json={"name": "Other"}).json()["id"]
    tx(
        api,
        account_id=other,
        instrument_id=book["fund"],
        type="buy",
        trade_date="2024-01-03",
        quantity="2",
        price="101",
    )
    assert point(db, "2024-01-12").value_eur == 1188 + 2 * 108
    assert point(db, "2024-01-12", account_id=book["account"]).value_eur == 1188
    assert point(db, "2024-01-12", account_id=other).value_eur == 216


# --- the summary (FR-PF-01) --------------------------------------------------------------------


def summary(api: TestClient, period: str, **extra: Any) -> dict[str, Any]:
    query = "&".join(f"{k}={v}" for k, v in {"period": period, "as_of": AS_OF, **extra}.items())
    r = api.get(f"/api/v1/portfolio/summary?{query}")
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def ratio(a: str | None, num: int | Decimal, den: int | Decimal) -> bool:
    return a is not None and abs(Decimal(a) - D(num) / D(den)) < D("1E-12")


def test_the_totals_match_a_hand_computation(api: TestClient, book: dict[str, Any]) -> None:
    s = summary(api, "MAX")
    assert s["as_of"] == AS_OF and s["price_date"] == AS_OF and s["account_id"] is None
    assert D(s["value_eur"]) == 1188 and D(s["net_contributions_eur"]) == 1098
    assert D(s["income_eur"]) == 3 and D(s["costs_eur"]) == 0
    assert D(s["total_pnl_eur"]) == 93 and ratio(s["total_pnl_ratio"], 93, 1098)
    assert s["cash_eur"] is None and s["unvalued_positions"] == 0  # cash tracking is off


@pytest.mark.parametrize(
    ("period", "start", "flows", "pnl", "capital"),
    [
        ("1D", "2024-01-11", 0, 11, 1177),  # 11 units gained 1 each
        ("1W", "2024-01-05", 97, 64, 1127),  # (1188-1030) - 97 put in + 3 income
        ("MAX", "2024-01-01", 1098, 93, 1098),
        ("1M", "2023-12-12", 1098, 93, 1098),  # starts before the first transaction
        ("YTD", "2023-12-31", 1098, 93, 1098),
    ],
)
def test_period_figures_update_with_the_period(
    api: TestClient,
    book: dict[str, Any],
    period: str,
    start: str,
    flows: int,
    pnl: int,
    capital: int,
) -> None:
    p = summary(api, period)["period"]
    assert (p["key"], p["start"], p["end"]) == (period, start, AS_OF)
    assert (
        D(p["net_flows_eur"]) == flows
        and D(p["pnl_eur"]) == pnl
        and ratio(p["pnl_ratio"], pnl, capital)
    )
    assert D(p["value_end_eur"]) == 1188


def test_a_custom_period_and_the_day_change(api: TestClient, book: dict[str, Any]) -> None:
    s = summary(api, "custom", **{"from": "2024-01-03", "to": "2024-01-10"})
    p = s["period"]
    # 3 to 10 January: value 1010 -> 1590, 520 put in, 3 income -> (580) - 520 + 3 = 63 on 1530
    assert (p["start"], p["end"]) == ("2024-01-03", "2024-01-10") and s["as_of"] == "2024-01-10"
    assert D(p["pnl_eur"]) == 63 and ratio(p["pnl_ratio"], 63, 1530)
    assert (
        D(s["day_change"]["pnl_eur"]) == 18
    )  # 10 Jan vs 9 Jan: 15 units up by 1 each, plus the 3 dividend
    full = summary(api, "1M")
    assert D(full["day_change"]["pnl_eur"]) == 11 and ratio(
        full["day_change"]["pnl_ratio"], 11, 1177
    )


def test_the_summary_agrees_with_the_positions_api(api: TestClient, book: dict[str, Any]) -> None:
    positions = api.get(f"/api/v1/positions?as_of={AS_OF}").json()["totals"]
    s = summary(api, "MAX")
    assert D(positions["market_value_eur"]) == D(s["value_eur"])  # two code paths, one number


def test_summary_per_account_and_for_an_empty_portfolio(
    api: TestClient, book: dict[str, Any]
) -> None:
    other = api.post("/api/v1/accounts", json={"name": "Other"}).json()["id"]
    empty = summary(api, "MAX", account=other)
    assert (
        D(empty["value_eur"]) == 0
        and empty["total_pnl_ratio"] is None
        and empty["price_date"] is None
    )
    assert empty["period"]["pnl_ratio"] is None and empty["account_id"] == other
    mine = summary(api, "MAX", account=book["account"])
    assert D(mine["value_eur"]) == 1188


def test_summary_input_errors_are_explained(api: TestClient, book: dict[str, Any]) -> None:
    bad = api.get("/api/v1/portfolio/summary?period=week")
    assert bad.status_code == 422 and "Unknown period 'WEEK'" in bad.json()["detail"]
    custom = api.get("/api/v1/portfolio/summary?period=custom")
    assert custom.status_code == 422 and "needs both a start and an end" in custom.json()["detail"]
    assert api.get("/api/v1/portfolio/summary?account=999").status_code == 404


def test_requires_login(client: TestClient) -> None:
    assert client.get("/api/v1/portfolio/summary").status_code == 401
    assert client.get("/api/v1/portfolio/history").status_code == 401


# --- snapshots (FR-PF-10) ----------------------------------------------------------------------


def ctx_for(settings: Settings, today: str):  # type: ignore[no-untyped-def]
    return make_ctx(settings, [], now=datetime.fromisoformat(today).replace(tzinfo=UTC))


def snapshot_rows(db) -> list[tuple[Any, ...]]:  # type: ignore[no-untyped-def]
    db.expire_all()
    rows = db.scalars(select(PortfolioSnapshot).order_by(PortfolioSnapshot.date))
    return [
        (r.date, r.total_value_eur, r.net_contributions_eur, r.income_eur, r.costs_eur, r.unvalued_positions,
         r.positions, r.is_peildatum, r.locked)
        for r in rows
    ]  # fmt: skip


def test_the_nightly_job_writes_a_snapshot_for_every_day_from_the_first_transaction(
    settings: Settings, book: dict[str, Any], db
) -> None:  # type: ignore[no-untyped-def]
    result = snapshots_job(ctx_for(settings, "2024-01-15"))
    assert result.status == "ok" and "14 snapshot day(s) written from 2024-01-02" in result.log
    db.expire_all()
    rows = {r.date: r for r in db.scalars(select(PortfolioSnapshot))}
    assert min(rows) == date(2024, 1, 2) and max(rows) == date(2024, 1, 15) and len(rows) == 14
    assert (
        rows[date(2024, 1, 2)].total_value_eur,
        rows[date(2024, 1, 2)].net_contributions_eur,
    ) == (1000, 1001)
    assert (
        rows[date(2024, 1, 6)].total_value_eur == 1030
        and rows[date(2024, 1, 7)].total_value_eur == 1030
    )  # the weekend
    last = rows[date(2024, 1, 11)]
    assert (last.total_value_eur, last.net_contributions_eur, last.income_eur) == (1177, 1098, 3)
    (held,) = last.positions
    assert (
        held["quantity"] == "11" and held["price"] == "107" and held["price_date"] == "2024-01-11"
    )
    assert held["value_eur"] == "1177" and Decimal(held["cost_basis_eur"]) == D(
        "1120.6"
    )  # 6 left of lot 1 (600.6) + lot 2 (520)
    assert all(r.cash_eur == 0 and r.unvalued_positions == 0 for r in rows.values())


def test_rerunning_the_snapshot_job_is_idempotent(
    settings: Settings, book: dict[str, Any], db
) -> None:  # type: ignore[no-untyped-def]
    ctx = ctx_for(settings, "2024-01-15")
    snapshots_job(ctx)
    first = snapshot_rows(db)
    snapshots_job(ctx)  # nightly: refreshes the last week
    snapshots_job(ctx, from_date=date(2024, 1, 2))  # full recompute
    assert snapshot_rows(db) == first and len(first) == 14


def test_a_backdated_buy_changes_the_historical_snapshots(
    settings: Settings, book: dict[str, Any], api: TestClient, db
) -> None:  # type: ignore[no-untyped-def]
    ctx = ctx_for(settings, "2024-01-15")
    snapshots_job(ctx)
    before = {r[0]: (r[1], r[2]) for r in snapshot_rows(db)}
    db.query(JobRequest).delete()
    db.commit()

    # a purchase entered now, dated 3 January: 2 units at 101
    tx(
        api,
        account_id=book["account"],
        instrument_id=book["fund"],
        type="buy",
        trade_date="2024-01-03",
        quantity="2",
        price="101",
    )
    request = db.scalars(select(JobRequest).where(JobRequest.job == "snapshots")).one()
    assert request.params == {"from": "2024-01-03"}  # the ledger change queued exactly this
    snapshots_job(ctx, from_date=date.fromisoformat(request.params["from"]))

    after = {r[0]: (r[1], r[2]) for r in snapshot_rows(db)}
    assert after[date(2024, 1, 2)] == before[date(2024, 1, 2)]  # earlier days are untouched
    assert before[date(2024, 1, 3)] == (1010, 1001)
    assert after[date(2024, 1, 3)] == (1212, 1203)  # 12 units x 101; 202 more put in
    assert after[date(2024, 1, 12)][0] == before[date(2024, 1, 12)][0] + 2 * 108


def test_snapshots_before_any_transaction_and_without_prices(settings: Settings, db) -> None:  # type: ignore[no-untyped-def]
    assert "No transactions yet" in snapshots_job(ctx_for(settings, "2024-01-15")).log
    assert db.query(PortfolioSnapshot).count() == 0


def test_the_first_of_january_is_the_peildatum_and_locks_when_the_year_closes(
    settings: Settings, api: TestClient, db
) -> None:  # type: ignore[no-untyped-def]
    fund, listing = make_listing(db, ticker="P")
    add_bars(db, listing.id, {"2023-12-29": "100", "2024-01-02": "110", "2024-12-30": "130"})
    account = api.post("/api/v1/accounts", json={"name": "A"}).json()["id"]
    tx(
        api,
        account_id=account,
        instrument_id=fund.id,
        type="buy",
        trade_date="2023-12-15",
        quantity="10",
        price="95",
    )

    snapshots_job(ctx_for(settings, "2024-02-01"))
    jan1 = db.scalars(
        select(PortfolioSnapshot).where(PortfolioSnapshot.date == date(2024, 1, 1))
    ).one()
    assert jan1.is_peildatum and not jan1.locked  # the year has not closed yet
    assert jan1.total_value_eur == 1000  # the last close on or before 1 January (29 December)
    assert db.query(PortfolioSnapshot).filter_by(is_peildatum=True).count() == 1

    result = snapshots_job(ctx_for(settings, "2025-01-02"))  # the next year: 2024 has closed
    assert "peildatum snapshot(s) locked" in result.log
    db.expire_all()
    assert (
        db.scalars(select(PortfolioSnapshot).where(PortfolioSnapshot.date == date(2024, 1, 1)))
        .one()
        .locked
    )

    # a later correction to the ledger does not rewrite the filed reference value...
    tx(
        api,
        account_id=account,
        instrument_id=fund.id,
        type="buy",
        trade_date="2023-12-20",
        quantity="1",
        price="95",
    )
    snapshots_job(ctx_for(settings, "2025-01-02"), from_date=date(2023, 12, 15))
    db.expire_all()
    filed = db.scalars(
        select(PortfolioSnapshot).where(PortfolioSnapshot.date == date(2024, 1, 1))
    ).one()
    assert filed.total_value_eur == 1000 and filed.locked
    other_day = db.scalars(
        select(PortfolioSnapshot).where(PortfolioSnapshot.date == date(2024, 1, 3))
    ).one()
    assert other_day.total_value_eur == 1210  # 11 units x 110: ordinary days are corrected

    # ...unless that is asked for explicitly
    valuation = Valuation.load(db)
    save_snapshots(
        db, valuation, date(2024, 1, 1), date(2024, 1, 1), date(2025, 1, 2), include_locked=True
    )
    db.commit()
    db.expire_all()
    assert (
        db.scalars(select(PortfolioSnapshot).where(PortfolioSnapshot.date == date(2024, 1, 1)))
        .one()
        .total_value_eur
        == 1100
    )


def test_locking_only_touches_closed_years(db) -> None:  # type: ignore[no-untyped-def]
    for year in (2023, 2024):
        db.add(
            PortfolioSnapshot(
                date=date(year, 1, 1),
                total_value_eur=D(1),
                net_contributions_eur=D(1),
                is_peildatum=True,
            )
        )
    db.add(
        PortfolioSnapshot(date=date(2024, 2, 1), total_value_eur=D(1), net_contributions_eur=D(1))
    )
    db.commit()
    assert lock_closed_years(db, date(2024, 6, 1)) == 1  # only 2023 has closed
    assert lock_closed_years(db, date(2024, 6, 1)) == 0  # and running again changes nothing
    locked = {r.date: r.locked for r in db.scalars(select(PortfolioSnapshot))}
    assert locked == {date(2023, 1, 1): True, date(2024, 1, 1): False, date(2024, 2, 1): False}


def test_history_runs_from_the_first_transaction_with_index_and_drawdown(
    api: TestClient, book: dict[str, Any]
) -> None:
    rows = api.get("/api/v1/portfolio/history", params={"as_of": "2024-01-15"}).json()
    assert [r["date"] for r in rows] == [
        "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08",
        "2024-01-09", "2024-01-10", "2024-01-11", "2024-01-12", "2024-01-15",
    ]  # fmt: skip
    assert D(rows[0]["value_eur"]) == 1000 and D(rows[0]["net_contributions_eur"]) == 1001
    window = api.get(
        "/api/v1/portfolio/history",
        params={"from": "2024-01-10", "to": "2024-01-11", "as_of": "2024-01-15"},
    ).json()
    assert [(r["date"], D(r["value_eur"]), D(r["net_contributions_eur"])) for r in window] == [
        ("2024-01-10", D(1590), D(1521)),
        ("2024-01-11", D(1177), D(1098)),
    ]
    assert rows[0]["is_peildatum"] is False and rows[0]["unvalued_positions"] == 0

    # the index chains the daily returns; flows come in at the start of their day, income counts
    expected = Fraction(1030, 1001) * Fraction(1593, 1550) * Fraction(1188, 1167)
    assert abs(D(rows[-1]["twr_index"]) - D(expected.numerator) / D(expected.denominator)) < D(
        "1E-20"
    )
    assert all(D(r["drawdown"]) <= 0 for r in rows) and D(rows[-1]["drawdown"]) == 0


def test_history_flags_the_first_of_january_and_can_follow_one_account(
    api: TestClient, book: dict[str, Any]
) -> None:
    rows = api.get("/api/v1/portfolio/history", params={"as_of": "2025-01-15"}).json()
    peildatum = [r for r in rows if r["is_peildatum"]]
    assert [(r["date"], D(r["value_eur"])) for r in peildatum] == [("2025-01-01", D(1188))]
    one = api.get(
        "/api/v1/portfolio/history", params={"as_of": "2024-01-15", "account": book["account"]}
    ).json()
    assert len(one) == 10
    assert api.get("/api/v1/portfolio/history", params={"account": 999}).status_code == 404


# --- cash tracking (FR-TX-09) -------------------------------------------------------------------


def test_an_account_that_tracks_cash_values_its_cash_and_counts_only_deposits(  # type: ignore[no-untyped-def]
    api: TestClient, db
) -> None:
    fund, listing = make_listing(db, ticker="F")
    for bar in bars_for("XETR", date(2024, 1, 1), date(2024, 1, 12)):
        db.add(PriceBar(listing_id=listing.id, date=bar.date, close=bar.close, source="x"))
    db.commit()
    account = api.post("/api/v1/accounts", json={"name": "Cash", "track_cash": True}).json()
    assert account["track_cash"] is True
    a = account["id"]
    tx(api, account_id=a, type="deposit", trade_date="2024-01-02", net_amount_eur="5000")
    tx(
        api,
        account_id=a,
        instrument_id=fund.id,
        type="buy",
        trade_date="2024-01-02",
        quantity="10",
        price="100",
        fees="1",
    )
    summary = api.get("/api/v1/portfolio/summary", params={"period": "MAX", "as_of": AS_OF}).json()
    # 10 units x 108 plus 5000 - 1001 in cash; only the deposit counts as money put in
    assert D(summary["value_eur"]) == D("5079")
    assert D(summary["cash_eur"]) == D("3999")
    assert D(summary["net_contributions_eur"]) == D("5000")
    assert D(summary["total_pnl_eur"]) == D("79")  # 80 of price gain less the 1 fee


def test_the_summary_hides_cash_while_no_account_tracks_it(
    api: TestClient, book: dict[str, Any]
) -> None:
    summary = api.get("/api/v1/portfolio/summary", params={"as_of": AS_OF}).json()
    assert summary["cash_eur"] is None


def test_switching_cash_tracking_is_audited_and_rebuilds_the_snapshots(  # type: ignore[no-untyped-def]
    api: TestClient, book: dict[str, Any], db
) -> None:
    r = api.patch(f"/api/v1/accounts/{book['account']}", json={"track_cash": True})
    assert r.status_code == 200 and r.json()["track_cash"] is True
    request = db.scalars(
        select(JobRequest).where(JobRequest.job == "snapshots").order_by(JobRequest.id.desc())
    ).first()
    assert request is not None and request.job == "snapshots"
    assert request.params == {"from": "2024-01-02"}  # the first transaction of the account
    audit = api.get("/api/v1/audit", params={"entity": "account"}).json()["items"]
    assert any(e["diff"] == {"track_cash": {"old": False, "new": True}} for e in audit)


def test_the_price_status_says_when_prices_were_last_checked(
    api: TestClient,
    book: dict[str, Any],
    db,  # type: ignore[no-untyped-def]
) -> None:
    """Home shows how fresh the prices behind its figures are."""

    status = api.get("/api/v1/portfolio/price-status").json()
    assert status["newest_close"] == "2024-01-12" and status["last_checked_at"] is None
    assert (status["holdings_priced"], status["holdings_total"]) == (1, 1)
    db.add(JobRun(job="eod", params={}, status="ok", finished_at=utcnow()))
    db.add(JobRun(job="news", params={}, status="ok", finished_at=utcnow()))  # not a price job
    db.commit()
    assert api.get("/api/v1/portfolio/price-status").json()["last_checked_at"] is not None
