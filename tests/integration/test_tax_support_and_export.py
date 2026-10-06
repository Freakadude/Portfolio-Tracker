# ruff: noqa: F811  (the fixtures are imported from other test modules and used as parameters)
"""The annual tax-support report (FR-PF-11) and the export of transactions and positions
(FR-TX-13).

The book is the one of test_reports_and_batch (one fund F, euro, FIFO), with closes added:

    2023-12-29 close 105     2024-12-31 close 125     (and 2025-12-31 close 150)

2024, by hand: value on 1 January 10 x 105 = 1050, cost 1001, unrealized 49. Value on 31 December
3 x 125 = 375, cost 330, unrealized 45, change -4. Money put in 550 (the June purchase), taken out
479 + 1038 = 1517. Income 25 gross, 3 withheld. Costs of trading 1 + 2 = 3, other fees 2.50.
Realized: proceeds 1517, cost 1221, result 296.
"""

import csv
import io
import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.db.models_ledger import LedgerTransaction, PriceBar
from folio.imports.mapping import FOLIO_HEADERS, detect_preset
from folio.reports import history_years
from tests.integration.test_reports_and_batch import api, book, db, tx  # noqa: F401
from tests.marketdata_helpers import make_listing

D = Decimal


def bar(db: Session, instrument_id: int, day: str, close: str) -> None:
    from folio.db.models_ledger import Listing

    listing = db.scalars(select(Listing).where(Listing.instrument_id == instrument_id)).one()
    db.add(
        PriceBar(
            listing_id=listing.id,
            date=date.fromisoformat(day),
            open=D(close),
            high=D(close),
            low=D(close),
            close=D(close),
            volume=0,
            source="fake",
        )
    )


@pytest.fixture
def priced(book, db: Session) -> dict[str, Any]:
    for day, close in (("2023-12-29", "105"), ("2024-12-31", "125"), ("2025-12-31", "150")):
        bar(db, book["fund"], day, close)
    db.commit()
    return book


# --- the tax-support report -----------------------------------------------------------------------


def test_the_report_for_2024_matches_a_hand_computation(api: TestClient, priced) -> None:
    r = api.get("/api/v1/reports/tax-support", params={"year": 2024}).json()
    assert (r["start"], r["end"], r["partial"]) == ("2024-01-01", "2024-12-31", False)
    assert (D(r["value_start_eur"]), D(r["value_end_eur"])) == (D(1050), D(375))
    assert (D(r["unrealized_start_eur"]), D(r["unrealized_end_eur"])) == (D(49), D(45))
    assert D(r["unrealized_change_eur"]) == D(-4)
    assert (D(r["money_in_eur"]), D(r["money_out_eur"]), D(r["net_contributions_eur"])) == (
        D(550),
        D(1517),
        D(-967),
    )
    assert (D(r["income_gross_eur"]), D(r["withholding_eur"]), D(r["income_net_eur"])) == (
        D(25),
        D(3),
        D(22),
    )
    assert (D(r["trade_costs_eur"]), D(r["other_costs_eur"])) == (D(3), D("2.5"))
    assert (
        D(r["realized_proceeds_eur"]),
        D(r["realized_cost_eur"]),
        D(r["realized_result_eur"]),
    ) == (
        D(1517),
        D(1221),
        D(296),
    )
    (start,) = r["holdings_start"]
    assert (start["instrument"], D(start["quantity"]), D(start["value_eur"])) == (
        "F fund",
        10,
        1050,
    )
    assert D(start["cost_basis_eur"]) == D(1001)
    (end,) = r["holdings_end"]
    assert (D(end["quantity"]), D(end["value_eur"]), D(end["cost_basis_eur"])) == (3, 375, 330)
    assert "not tax advice" in r["note"]
    # the realized part agrees with the existing yearly report
    realized = api.get("/api/v1/reports/realized", params={"year": 2024}).json()
    assert D(realized["realized_total_eur"]) == D(r["realized_result_eur"])


def test_a_year_before_the_first_trade_starts_at_nothing_and_2025_follows_2024(
    api: TestClient, priced
) -> None:
    first = api.get("/api/v1/reports/tax-support", params={"year": 2023}).json()
    assert D(first["value_start_eur"]) == 0 and first["holdings_start"] == []
    assert D(first["money_in_eur"]) == D(1001)  # the December purchase, fee included
    follow = api.get("/api/v1/reports/tax-support", params={"year": 2025}).json()
    assert D(follow["value_start_eur"]) == D(375)  # where 2024 ended
    assert (D(follow["realized_result_eur"]), D(follow["money_out_eur"])) == (D(30), D(140))
    assert D(follow["value_end_eur"]) == D(300)  # 2 units x 150


def test_the_current_year_is_marked_partial_and_runs_to_today(api: TestClient, priced) -> None:
    this_year = date.today().year
    r = api.get("/api/v1/reports/tax-support", params={"year": this_year}).json()
    assert r["partial"] is True and r["end"] == date.today().isoformat()


def test_an_account_filter_limits_the_report_and_unknown_ones_are_refused(
    api: TestClient, priced, db: Session
) -> None:
    other = api.post("/api/v1/accounts", json={"name": "Second"}).json()["id"]
    empty = api.get("/api/v1/reports/tax-support", params={"year": 2024, "account": other}).json()
    assert D(empty["value_end_eur"]) == 0 and empty["holdings_end"] == []
    mine = api.get(
        "/api/v1/reports/tax-support", params={"year": 2024, "account": priced["account"]}
    ).json()
    assert D(mine["value_end_eur"]) == D(375)
    assert (
        api.get("/api/v1/reports/tax-support", params={"year": 2024, "account": 999}).status_code
        == 404
    )
    assert api.get("/api/v1/reports/tax-support", params={"year": 1800}).status_code == 422


def test_the_csv_has_the_summary_and_both_lists_of_positions(api: TestClient, priced) -> None:
    r = api.get("/api/v1/reports/tax-support", params={"year": 2024, "format": "csv"})
    assert r.headers["content-type"].startswith("text/csv")
    assert 'filename="folio-tax-support-2024.csv"' in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == ["section", "item", "isin", "quantity", "value_eur", "cost_basis_eur"]
    summary = {row[1]: row[4] for row in rows if row[0] == "summary"}
    assert D(summary["Value on 2024-01-01"]) == 1050 and D(summary["Value on 2024-12-31"]) == 375
    assert D(summary["Realized result"]) == 296 and D(summary["Costs of buying and selling"]) == 3
    assert D(summary["Change in unrealized result"]) == -4
    assert [row for row in rows if row[0] == "holding_end"][0][3:] == ["3", "375", "330"]


def test_the_years_to_choose_from_run_from_the_first_trade(db: Session, priced) -> None:
    assert history_years(db, date(2025, 6, 1)) == [2025, 2024, 2023]
    assert history_years(db, date(2023, 12, 31)) == [2023]


def test_the_report_needs_a_login(client: TestClient, owner: None) -> None:
    assert client.get("/api/v1/reports/tax-support").status_code == 401
    assert client.get("/api/v1/reports/tax-years").status_code == 401


# --- the export -----------------------------------------------------------------------------------


def parsed(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def test_the_transactions_csv_has_exactly_the_columns_the_import_recognises(
    api: TestClient, priced
) -> None:
    r = api.get("/api/v1/export/transactions")
    assert r.headers["content-type"].startswith("text/csv")
    assert (
        f'filename="folio-transactions-{date.today().isoformat()}.csv"'
        in r.headers["content-disposition"]
    )
    rows = parsed(r.text)
    assert len(rows) == 8 and list(rows[0]) == list(FOLIO_HEADERS)
    assert detect_preset(list(rows[0])) == "folio"
    first = rows[0]
    assert (first["date"], first["type"], first["isin"], first["quantity"], first["price"]) == (
        "2023-12-01",
        "buy",
        "IE00B5BMR087",
        "10",
        "100",
    )
    assert (first["fees"], first["fees_currency"], first["fx_rate_to_eur"]) == ("1", "EUR", "")
    dividend = next(x for x in rows if x["type"] == "dividend")
    assert (dividend["amount"], dividend["taxes"], dividend["quantity"]) == ("20", "3", "")
    interest = next(x for x in rows if x["type"] == "interest")
    assert interest["isin"] == "" and interest["amount"] == "5"
    assert all(x["reference"].startswith("folio-") for x in rows)


def test_the_transactions_json_is_the_same_rows_with_the_date(api: TestClient, priced) -> None:
    doc = json.loads(api.get("/api/v1/export/transactions", params={"format": "json"}).text)
    assert doc["exported_on"] == date.today().isoformat() and len(doc["transactions"]) == 8
    assert doc["transactions"][0]["type"] == "buy"


def test_only_posted_transactions_and_only_the_chosen_account_are_exported(
    api: TestClient, priced, db: Session
) -> None:
    other = api.post("/api/v1/accounts", json={"name": "Second"}).json()["id"]
    tx(
        api,
        account_id=other,
        instrument_id=priced["fund"],
        type="buy",
        trade_date="2024-02-01",
        quantity="1",
        price="100",
    )
    draft = tx(
        api,
        account_id=other,
        instrument_id=priced["fund"],
        type="buy",
        trade_date="2024-02-02",
        quantity="1",
        price="100",
    )
    row = db.get(LedgerTransaction, draft["id"])
    row.status = "draft"
    db.commit()
    everything = api.get("/api/v1/export/transactions", params={"format": "json"}).json()
    assert len(everything["transactions"]) == 9  # the 8, plus the one posted buy; not the draft
    only = api.get(
        "/api/v1/export/transactions", params={"account": other, "format": "json"}
    ).json()
    assert [t["date"] for t in only["transactions"]] == ["2024-02-01"]
    assert api.get("/api/v1/export/transactions", params={"account": 999}).status_code == 404


def test_the_positions_export_has_cost_basis_and_value(api: TestClient, priced) -> None:
    csv_rows = parsed(api.get("/api/v1/export/positions").text)
    assert len(csv_rows) == 1
    row = csv_rows[0]
    assert (row["instrument"], row["isin"], row["quantity"], row["account"]) == (
        "F fund",
        "IE00B5BMR087",
        "2",
        "Degiro",
    )
    assert D(row["cost_basis_eur"]) == D(220)  # 2 units left from lot B at 110
    assert D(row["market_value_eur"]) == D(300) and D(row["last_close"]) == D(150)
    doc = json.loads(api.get("/api/v1/export/positions", params={"format": "json"}).text)
    assert doc["positions"][0]["quantity"] == "2"


def test_a_spreadsheet_formula_in_a_name_or_note_is_neutralised(api: TestClient, priced) -> None:
    tx(
        api,
        account_id=priced["account"],
        instrument_id=priced["fund"],
        type="buy",
        trade_date="2025-03-01",
        quantity="1",
        price="140",
        note='=HYPERLINK("http://x")',
    )
    rows = parsed(api.get("/api/v1/export/transactions").text)
    assert rows[-1]["note"].startswith("'=")


def test_exports_need_a_login(client: TestClient, owner: None) -> None:
    assert client.get("/api/v1/export/transactions").status_code == 401
    assert client.get("/api/v1/export/positions").status_code == 401


# --- the round trip (FR-TX-13: the export re-imports cleanly through FR-TX-07) --------------------


def test_the_export_reads_back_into_another_account_with_identical_positions(
    api: TestClient, priced, db: Session
) -> None:
    # a dollar fund with a broker rate and a tax, a deposit, to cover the awkward columns
    usd, _ = make_listing(db, ticker="U", currency="USD", isin="US0378331005")
    db.commit()
    account = priced["account"]
    tx(api, account_id=account, instrument_id=usd.id, type="buy", trade_date="2024-04-01",
       quantity="7", price="12.3456", currency="USD", fx_rate_to_eur="0.9234567", fees="0.55",
       fees_currency="EUR", taxes="0.25")  # fmt: skip
    tx(api, account_id=account, instrument_id=usd.id, type="dividend", trade_date="2024-05-01",
       net_amount_eur="3.21", taxes="0.48")  # fmt: skip
    tx(api, account_id=account, type="deposit", trade_date="2024-06-15", net_amount_eur="500")
    exported = api.get("/api/v1/export/transactions").content

    second = api.post("/api/v1/accounts", json={"name": "Copy"}).json()["id"]
    preview = api.post(
        "/api/v1/imports",
        data={"account_id": str(second)},
        files={"file": ("folio-transactions.csv", exported, "text/csv")},
    )
    assert preview.status_code == 201, preview.text
    body = preview.json()
    assert body["detected_preset"] == "folio"
    assert body["mapping"]["type_mode"] == "column" and body["mapping"]["fx_semantics"] == "to_eur"
    batch = body["batch"]["id"]
    dry = api.put(f"/api/v1/imports/{batch}/mapping", json={"mapping": body["mapping"]}).json()
    assert dry["counts"] == {"new": 11, "duplicate": 0, "error": 0, "skipped": 0}, dry
    done = api.post(f"/api/v1/imports/{batch}/commit", json={})
    assert done.status_code == 200 and done.json()["rows_imported"] == 11

    from folio.db.models_ledger import Position

    db.expire_all()
    positions = {
        (p.account_id, p.instrument_id): p
        for p in db.scalars(select(Position).where(Position.account_id.in_((account, second))))
    }
    for instrument_id in (priced["fund"], usd.id):
        a, b = positions[(account, instrument_id)], positions[(second, instrument_id)]
        assert (a.quantity, a.cost_basis_eur, a.realized_pnl_eur, a.income_eur) == (
            b.quantity,
            b.cost_basis_eur,
            b.realized_pnl_eur,
            b.income_eur,
        ), instrument_id
    # and the same again from the file the copy now exports
    again = api.get("/api/v1/export/transactions", params={"account": second}).text
    original = api.get("/api/v1/export/transactions", params={"account": account}).text
    strip = lambda text: [  # noqa: E731
        {k: v for k, v in r.items() if k not in ("account", "reference")} for r in parsed(text)
    ]
    assert strip(again) == strip(original)
