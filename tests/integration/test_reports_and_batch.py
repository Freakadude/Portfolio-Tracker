"""Realized and income report (FR-TX-12), quick-add batches (FR-TX-11) and reconciliation (FR-TX-10).

The report's book (one fund F, euro, FIFO, hand-computed):

    2023-12-01 buy 10 @ 100, fee 1               lot A: 10 units, cost 1001
    2024-03-01 sell 4 @ 120, fee 1  -> net 479   from A: cost 400.4, result 78.6
    2024-03-15 dividend 20, tax 3
    2024-06-01 buy 5 @ 110                       lot B: 5 units, cost 550
    2024-09-01 sell 8 @ 130, fee 2  -> net 1038  6 from A (600.6) + 2 from B (220): result 217.4
    2024-11-01 interest 5 (no instrument)
    2024-12-01 fee 2.50
    2025-02-01 sell 1 @ 140                      from B: cost 110, result 30
"""

import csv
import io
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import AuditLog
from folio.db.models_ledger import JobRequest, LedgerTransaction
from tests.conftest import PASSWORD, USERNAME
from tests.marketdata_helpers import make_listing

D = Decimal


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


@pytest.fixture
def book(api: TestClient, db) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    fund, _ = make_listing(db, ticker="F")
    db.commit()
    a = api.post("/api/v1/accounts", json={"name": "Degiro"}).json()["id"]
    f = fund.id
    common = {"account_id": a, "instrument_id": f}
    tx(api, **common, type="buy", trade_date="2023-12-01", quantity="10", price="100", fees="1")
    tx(api, **common, type="sell", trade_date="2024-03-01", quantity="4", price="120", fees="1")
    tx(api, **common, type="dividend", trade_date="2024-03-15", net_amount_eur="20", taxes="3")
    tx(api, **common, type="buy", trade_date="2024-06-01", quantity="5", price="110")
    tx(api, **common, type="sell", trade_date="2024-09-01", quantity="8", price="130", fees="2")
    tx(api, account_id=a, type="interest", trade_date="2024-11-01", net_amount_eur="5")
    tx(api, account_id=a, type="fee", trade_date="2024-12-01", net_amount_eur="2.5")
    tx(api, **common, type="sell", trade_date="2025-02-01", quantity="1", price="140")
    return {"account": a, "fund": f}


# --- the yearly report --------------------------------------------------------------------------


def test_the_report_for_a_year_matches_a_hand_computation(api, book) -> None:  # type: ignore[no-untyped-def]
    r = api.get("/api/v1/reports/realized", params={"year": 2024}).json()
    [row] = r["realized"]
    assert (row["account"], row["instrument"], D(row["quantity"])) == ("Degiro", "F fund", 12)
    assert (D(row["proceeds_eur"]), D(row["cost_eur"]), D(row["result_eur"])) == (
        D(1517),
        D(1221),
        D(296),
    )
    assert D(r["realized_total_eur"]) == 296  # 78.6 + 217.4
    income = {i["instrument"]: i for i in r["income"]}
    assert (D(income["F fund"]["gross_eur"]), D(income["F fund"]["withholding_eur"])) == (20, 3)
    assert D(income["F fund"]["net_eur"]) == 17
    assert (D(income["Interest"]["gross_eur"]), D(income["Interest"]["net_eur"])) == (5, 5)
    assert (D(r["income_gross_eur"]), D(r["withholding_eur"]), D(r["costs_eur"])) == (
        25,
        3,
        D("2.5"),
    )


def test_a_year_only_counts_its_own_sales(api, book) -> None:  # type: ignore[no-untyped-def]
    r = api.get("/api/v1/reports/realized", params={"year": 2025}).json()
    [row] = r["realized"]
    assert (
        D(row["quantity"]),
        D(row["proceeds_eur"]),
        D(row["cost_eur"]),
        D(row["result_eur"]),
    ) == (
        1,
        D(140),
        D(110),
        D(30),
    )
    assert r["income"] == [] and D(r["costs_eur"]) == 0
    empty = api.get("/api/v1/reports/realized", params={"year": 2023}).json()
    assert empty["realized"] == [] and D(empty["realized_total_eur"]) == 0  # the buy is no sale


def test_the_years_with_something_to_report(api, book) -> None:  # type: ignore[no-untyped-def]
    assert api.get("/api/v1/reports/years").json() == [2025, 2024]  # 2023 has only a purchase


def test_the_csv_export_has_the_same_figures(api, book) -> None:  # type: ignore[no-untyped-def]
    r = api.get("/api/v1/reports/realized", params={"year": 2024, "format": "csv"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'filename="folio-realized-2024.csv"' in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    realized = next(x for x in rows if x["section"] == "realized")
    assert (realized["instrument"], D(realized["realized_result_eur"])) == ("F fund", 296)
    assert D(realized["proceeds_eur"]) == 1517 and D(realized["cost_eur"]) == 1221
    income = [x for x in rows if x["section"] == "income"]
    assert sorted(D(x["income_gross_eur"]) for x in income) == [5, 20]
    total = next(x for x in rows if x["section"] == "total")
    assert (D(total["realized_result_eur"]), D(total["income_gross_eur"])) == (296, 25)
    assert next(x for x in rows if x["section"] == "costs")["realized_result_eur"] == "-2.5"


def test_names_that_look_like_formulas_are_made_harmless_in_the_csv(api, book, db) -> None:  # type: ignore[no-untyped-def]
    api.patch(f"/api/v1/accounts/{book['account']}", json={"name": "=HYPERLINK(1)"})
    text = api.get("/api/v1/reports/realized", params={"year": 2024, "format": "csv"}).text
    assert "'=HYPERLINK(1)" in text and ",=HYPERLINK" not in text


def test_the_report_can_follow_one_account(api, book) -> None:  # type: ignore[no-untyped-def]
    other = api.post("/api/v1/accounts", json={"name": "Other"}).json()["id"]
    mine = api.get(
        "/api/v1/reports/realized", params={"year": 2024, "account": book["account"]}
    ).json()
    theirs = api.get("/api/v1/reports/realized", params={"year": 2024, "account": other}).json()
    assert D(mine["realized_total_eur"]) == 296 and theirs["realized"] == []
    assert api.get("/api/v1/reports/realized", params={"account": 999}).status_code == 404
    assert api.get("/api/v1/reports/realized", params={"year": 1800}).status_code == 422


# --- quick-add batches --------------------------------------------------------------------------


def five_funds(db) -> list[int]:  # type: ignore[no-untyped-def]
    ids = [make_listing(db, ticker=f"E{n}", isin=None)[0].id for n in range(5)]
    db.commit()
    return ids


def buy(account: int, instrument: int, **extra: Any) -> dict[str, Any]:
    return {
        "account_id": account,
        "instrument_id": instrument,
        "type": "buy",
        "trade_date": "2024-01-02",
        "quantity": "3",
        "price": "50",
        **extra,
    }


def count(db) -> int:  # type: ignore[no-untyped-def]
    db.expire_all()
    return db.scalar(select(func.count()).select_from(LedgerTransaction)) or 0


def test_five_buys_are_saved_in_one_submit(api, db) -> None:  # type: ignore[no-untyped-def]
    ids = five_funds(db)
    account = api.post("/api/v1/accounts", json={"name": "Degiro"}).json()["id"]
    r = api.post(
        "/api/v1/transactions/batch", json={"transactions": [buy(account, i) for i in ids]}
    )
    assert r.status_code == 201, r.text
    assert [t["instrument_id"] for t in r.json()["created"]] == ids
    assert count(db) == 5
    positions = api.get("/api/v1/positions").json()["positions"]
    assert len(positions) == 5 and all(D(p["quantity"]) == 3 for p in positions)
    # one rebuild of the history for the whole batch, and every row audited
    requests = db.scalars(select(JobRequest).where(JobRequest.job == "snapshots")).all()
    assert len(requests) == 1 and requests[0].params == {"from": "2024-01-02"}
    audited = db.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.entity == "transaction", AuditLog.action == "create")
    )
    assert audited == 5


def test_one_bad_row_saves_nothing_and_every_problem_names_its_row(api, db) -> None:  # type: ignore[no-untyped-def]
    ids = five_funds(db)
    account = api.post("/api/v1/accounts", json={"name": "Degiro"}).json()["id"]
    rows = [buy(account, i) for i in ids]
    rows[2]["quantity"] = "0"
    rows[4]["instrument_id"] = 999
    r = api.post("/api/v1/transactions/batch", json={"transactions": rows})
    assert r.status_code == 422
    body = r.json()
    assert "Nothing was saved: 2 of 5 rows need fixing." in body["detail"]
    fields = {e["field"]: e["message"] for e in body["errors"]}
    assert "Row 3" in fields["rows.3.quantity"] and "greater than zero" in fields["rows.3.quantity"]
    assert "Row 5" in fields["rows.5.instrument_id"]
    assert count(db) == 0


def test_a_sale_the_batch_cannot_cover_saves_nothing(api, db) -> None:  # type: ignore[no-untyped-def]
    [fund, *_] = five_funds(db)
    account = api.post("/api/v1/accounts", json={"name": "Degiro"}).json()["id"]
    sell = {**buy(account, fund), "type": "sell", "trade_date": "2024-01-03", "quantity": "10"}
    r = api.post("/api/v1/transactions/batch", json={"transactions": [buy(account, fund), sell]})
    assert r.status_code == 422 and r.json()["detail"].startswith("Nothing was saved.")
    assert count(db) == 0


def test_a_batch_may_sell_what_it_buys_earlier(api, db) -> None:  # type: ignore[no-untyped-def]
    [fund, *_] = five_funds(db)
    account = api.post("/api/v1/accounts", json={"name": "Degiro"}).json()["id"]
    sell = {**buy(account, fund), "type": "sell", "trade_date": "2024-01-03", "quantity": "2"}
    r = api.post("/api/v1/transactions/batch", json={"transactions": [sell, buy(account, fund)]})
    assert r.status_code == 201, r.text  # the order in the list does not matter, the dates do
    [p] = api.get("/api/v1/positions").json()["positions"]
    assert D(p["quantity"]) == 1


def test_batch_sizes_are_bounded(api, db) -> None:  # type: ignore[no-untyped-def]
    [fund, *_] = five_funds(db)
    account = api.post("/api/v1/accounts", json={"name": "Degiro"}).json()["id"]
    assert api.post("/api/v1/transactions/batch", json={"transactions": []}).status_code == 422
    too_many = [buy(account, fund)] * 101
    assert (
        api.post("/api/v1/transactions/batch", json={"transactions": too_many}).status_code == 422
    )


# --- reconciliation -----------------------------------------------------------------------------


@pytest.fixture
def held(api: TestClient, db) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    one, _ = make_listing(db, ticker="ONE", isin="IE00B5BMR087")
    two, _ = make_listing(db, ticker="TWO", isin="NL0010273215")
    db.commit()
    a = api.post("/api/v1/accounts", json={"name": "Degiro"}).json()["id"]
    tx(
        api,
        account_id=a,
        instrument_id=one.id,
        type="buy",
        trade_date="2024-01-02",
        quantity="10",
        price="100",
    )
    tx(
        api,
        account_id=a,
        instrument_id=one.id,
        type="sell",
        trade_date="2024-01-05",
        quantity="4",
        price="101",
    )
    tx(
        api,
        account_id=a,
        instrument_id=two.id,
        type="buy",
        trade_date="2024-01-02",
        quantity="3",
        price="10",
    )
    return {"account": a, "one": one.id, "two": two.id}


def reconcile(api: TestClient, held: dict[str, Any], day: str, rows: list[dict[str, Any]]) -> Any:
    r = api.post(
        "/api/v1/transactions/reconcile",
        json={"account_id": held["account"], "date": day, "rows": rows},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_a_mismatch_highlights_the_instrument_and_the_size(api, held) -> None:  # type: ignore[no-untyped-def]
    out = reconcile(
        api,
        held,
        "2024-01-10",
        [
            {"isin": "IE00B5BMR087", "quantity": "7"},
            {"instrument_id": held["two"], "quantity": "3"},
        ],
    )
    assert (out["matches"], out["differences"]) == (1, 1)
    first = out["lines"][0]  # the difference comes first
    assert (first["name"], first["status"]) == ("ONE fund", "difference")
    assert (D(first["ours"]), D(first["broker"]), D(first["difference"])) == (6, 7, 1)
    assert out["lines"][1]["status"] == "match"


def test_reconciliation_is_as_of_the_chosen_date(api, held) -> None:  # type: ignore[no-untyped-def]
    before_sale = reconcile(api, held, "2024-01-04", [{"isin": "IE00B5BMR087", "quantity": "10"}])
    line = next(x for x in before_sale["lines"] if x["isin"] == "IE00B5BMR087")
    assert line["status"] == "match" and D(line["ours"]) == 10


def test_what_the_broker_does_not_list_and_what_we_do_not_know_are_reported(api, held) -> None:  # type: ignore[no-untyped-def]
    out = reconcile(
        api,
        held,
        "2024-01-10",
        [{"isin": "IE00B5BMR087", "quantity": "6"}, {"isin": "US0378331005", "quantity": "2"}],
    )
    by_status = {x["status"]: x for x in out["lines"]}
    assert by_status["missing_at_broker"]["name"] == "TWO fund"
    assert D(by_status["missing_at_broker"]["difference"]) == -3
    assert (
        by_status["unknown"]["isin"] == "US0378331005"
        and by_status["unknown"]["instrument_id"] is None
    )
    assert out["differences"] == 2 and out["matches"] == 1


def test_reconciliation_writes_nothing_and_checks_its_input(api, held, db) -> None:  # type: ignore[no-untyped-def]
    before = count(db)
    reconcile(api, held, "2024-01-10", [{"isin": "IE00B5BMR087", "quantity": "1"}])
    assert count(db) == before
    bad = api.post(
        "/api/v1/transactions/reconcile",
        json={"account_id": held["account"], "date": "2024-01-10", "rows": [{"quantity": "1"}]},
    )
    assert bad.status_code == 422
    gone = api.post(
        "/api/v1/transactions/reconcile",
        json={"account_id": 999, "date": "2024-01-10", "rows": [{"isin": "X", "quantity": "1"}]},
    )
    assert gone.status_code == 404


def test_requires_login(client: TestClient) -> None:
    assert client.get("/api/v1/reports/years").status_code == 401
    assert client.get("/api/v1/reports/realized").status_code == 401
    assert client.post("/api/v1/transactions/batch", json={"transactions": []}).status_code == 401
    assert client.post("/api/v1/transactions/reconcile", json={}).status_code == 401
