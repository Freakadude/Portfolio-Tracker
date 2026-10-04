"""CSV import wizard backend (FR-TX-07). The fixture files are fictional, never a real export."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import AuditLog
from folio.db.models_ledger import ImportBatch, JobRequest, LedgerTransaction, Position
from folio.marketdata.fx import to_eur_multiplier
from tests.conftest import PASSWORD, USERNAME
from tests.marketdata_helpers import make_listing

D = Decimal
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "imports"
SXR8, AAPL, ASML = "IE00B5BMR087", "US0378331005", "NL0010273215"


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


@pytest.fixture
def api(client: TestClient, owner: None) -> TestClient:
    client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return client


@pytest.fixture
def account(api: TestClient) -> int:
    return api.post("/api/v1/accounts", json={"name": "Degiro"}).json()["id"]  # type: ignore[no-any-return]


@pytest.fixture
def instruments(db) -> dict[str, int]:  # type: ignore[no-untyped-def]
    ids = {}
    for isin, ticker, currency in (
        (SXR8, "SXR8", "EUR"),
        (AAPL, "AAPL", "USD"),
        (ASML, "ASML", "EUR"),
    ):
        instrument, _ = make_listing(db, ticker=ticker, currency=currency, isin=isin)
        ids[isin] = instrument.id
    db.commit()
    return ids


def upload(
    api: TestClient,
    account_id: int,
    name: str = "degiro_transactions_nl.csv",
    data: bytes | None = None,
    **form: Any,
) -> Any:
    content = data if data is not None else (FIXTURES / name).read_bytes()
    return api.post(
        "/api/v1/imports",
        data={"account_id": str(account_id), **{k: str(v) for k, v in form.items()}},
        files={"file": (name, content, "text/csv")},
    )


def preview(api: TestClient, account_id: int, **kwargs: Any) -> dict[str, Any]:
    r = upload(api, account_id, **kwargs)
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def accept(api: TestClient, batch_id: int, mapping: dict[str, Any], **extra: Any) -> dict[str, Any]:
    r = api.put(f"/api/v1/imports/{batch_id}/mapping", json={"mapping": mapping, **extra})
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def position(db, account_id: int, instrument_id: int) -> Position:  # type: ignore[no-untyped-def]
    db.expire_all()
    return db.scalars(  # type: ignore[no-any-return]
        select(Position).where(
            Position.account_id == account_id, Position.instrument_id == instrument_id
        )
    ).one()


def test_requires_login(client: TestClient) -> None:
    assert client.get("/api/v1/imports").status_code == 401
    assert client.get("/api/v1/import-presets").status_code == 401


# --- upload and auto-detection --------------------------------------------------------------


def test_upload_detects_the_layout_of_a_dutch_export(api: TestClient, account: int) -> None:
    p = preview(api, account)
    assert (p["encoding"], p["delimiter"], p["row_count"], p["from_preset"]) == (
        "utf-8",
        ",",
        7,
        False,
    )
    assert (
        p["batch"]["status"] == "preview"
        and p["batch"]["file_name"] == "degiro_transactions_nl.csv"
    )
    labels = {h["index"]: h["label"] for h in p["headers"]}
    assert (
        labels[0] == "Datum" and labels[8] == "(column 9)" and labels[10] == "(column 11)"
    )  # unnamed columns
    assert len(p["headers"]) == 19 and len(p["sample_rows"]) == 7
    m = p["mapping"]
    assert (m["date_col"], m["time_col"], m["isin_col"], m["quantity_col"], m["price_col"]) == (
        0,
        1,
        3,
        6,
        7,
    )
    assert (
        m["currency_col"],
        m["fx_col"],
        m["fees_col"],
        m["fees_currency_col"],
        m["reference_col"],
    ) == (8, 13, 14, 15, 18)
    assert (m["decimal_separator"], m["thousands_separator"], m["date_format"], m["type_mode"]) == (
        ",",
        ".",
        "%d-%m-%Y",
        "sign",
    )


def test_upload_detects_dot_decimals_in_an_english_export(api: TestClient, account: int) -> None:
    m = preview(api, account, name="degiro_transactions_en.csv")["mapping"]
    assert (m["decimal_separator"], m["thousands_separator"]) == (".", ",")
    assert (m["quantity_col"], m["price_col"], m["fx_col"], m["reference_col"]) == (6, 7, 13, 18)


def test_upload_problems_are_explained(api: TestClient, account: int) -> None:
    empty = upload(api, account, data=b"")
    assert empty.status_code == 422 and "file is empty" in empty.json()["detail"]
    header_only = upload(api, account, data=b"Date,Quantity\n")
    assert "header row and at least one data row" in header_only.json()["detail"]
    huge = upload(api, account, data=b"a,b\n" + b"1,2\n" * (2 * 1024 * 1024))
    assert huge.status_code == 422 and "larger than 5 MB" in huge.json()["detail"]
    assert "account does not exist" in upload(api, 999).json()["detail"]
    assert "preset does not exist" in upload(api, account, preset_id=999).json()["detail"]
    assert (
        api.post("/api/v1/imports", data={"account_id": str(account)}).status_code == 422
    )  # no file


# --- dry run --------------------------------------------------------------------------------


def test_dry_run_reports_unknown_instruments_and_blocks_the_commit(
    api: TestClient, account: int
) -> None:
    p = preview(api, account)
    dry = accept(api, p["batch"]["id"], p["mapping"])
    assert dry["counts"] == {"new": 0, "duplicate": 0, "error": 7, "skipped": 0}
    assert dry["unknown_isins"] == [SXR8, AAPL, ASML] and dry["can_commit"] is False
    assert all("is not added yet" in r["reason"] for r in dry["rows"])
    commit = api.post(f"/api/v1/imports/{p['batch']['id']}/commit", json={})
    assert commit.status_code == 422 and "7 rows cannot be imported" in commit.json()["detail"]
    nothing = api.post(f"/api/v1/imports/{p['batch']['id']}/commit", json={"skip_errors": True})
    assert "nothing new to import" in nothing.json()["detail"]


def test_dry_run_classifies_every_row_without_writing(
    api: TestClient, account: int, instruments: dict[str, int], db
) -> None:  # type: ignore[no-untyped-def]
    p = preview(api, account)
    dry = accept(api, p["batch"]["id"], p["mapping"])
    assert (
        dry["counts"] == {"new": 7, "duplicate": 0, "error": 0, "skipped": 0}
        and dry["can_commit"] is True
    )
    rows = {r["row"]: r["summary"] for r in dry["rows"]}
    assert rows[2] == {"date": "2024-01-02", "type": "buy", "isin": SXR8, "quantity": "10", "price": "454.19",
                       "currency": "EUR", "amount_eur": "", "fees": "1.00"}  # fmt: skip
    assert rows[4]["type"] == "sell" and rows[4]["quantity"] == "8"  # negative quantity = sell
    assert rows[6]["price"] == "1050.25"  # the thousands separator was removed
    assert rows[5]["currency"] == "USD"
    assert db.query(LedgerTransaction).count() == 0  # a dry run writes nothing
    assert db.query(JobRequest).count() == 0


# --- commit, idempotence, undo ---------------------------------------------------------------


def commit_nl(api: TestClient, account: int) -> dict[str, Any]:
    p = preview(api, account)
    accept(api, p["batch"]["id"], p["mapping"])
    r = api.post(f"/api/v1/imports/{p['batch']['id']}/commit", json={})
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def test_commit_posts_the_rows_and_positions_match_hand_computed_values(
    api: TestClient,
    account: int,
    instruments: dict[str, int],
    db,  # type: ignore[no-untyped-def]
) -> None:
    batch = commit_nl(api, account)
    assert (
        batch["status"],
        batch["rows_total"],
        batch["rows_imported"],
        batch["rows_skipped"],
    ) == ("committed", 7, 7, 0)
    assert batch["committed_at"] is not None and batch["errors"] == []

    # S&P 500: 10 @ 454.19 + 1 fee, 5 @ 470.50 + 1 fee, sell 8 @ 480 - 2 fee (FIFO)
    #   consumed 8/10 of 4542.90 = 3634.32; net proceeds 3838; realized 203.68; 7 units left
    sxr8 = position(db, account, instruments[SXR8])
    assert (sxr8.quantity, sxr8.cost_basis_eur, sxr8.realized_pnl_eur) == (
        D(7),
        D("3262.08"),
        D("203.68"),
    )
    # Apple: 3 @ 190.25 USD at the file's rate of 1.0950 USD per euro, plus a 1 EUR fee
    aapl = position(db, account, instruments[AAPL])
    assert aapl.quantity == 3
    assert aapl.cost_basis_eur == D(3) * D("190.25") * to_eur_multiplier(D("1.0950")) + 1
    # ASML: 1 @ 1050.25 and two identical fills of 1 @ 1060 (each + 1 fee) all count
    asml = position(db, account, instruments[ASML])
    assert (asml.quantity, asml.cost_basis_eur) == (D(3), D("3173.25"))

    db.expire_all()
    txs = db.scalars(select(LedgerTransaction)).all()
    assert len(txs) == 7 and {t.source for t in txs} == {"import"}
    assert all(t.external_ref and t.external_ref.endswith(("#1", "#2")) for t in txs)
    assert len({t.external_ref for t in txs}) == 7  # the two identical fills got different keys
    assert {t.import_batch_id for t in txs} == {batch["id"]}

    stored = db.get(ImportBatch, batch["id"])
    assert stored is not None and "raw" not in (stored.config or {})  # the upload is dropped
    audit = db.scalars(select(AuditLog).where(AuditLog.entity == "import_batch")).one()
    assert (
        audit.action == "commit"
        and audit.diff["imported"] == 7
        and audit.diff["file"] == "degiro_transactions_nl.csv"
    )
    jobs = db.scalars(select(JobRequest).where(JobRequest.job == "snapshots")).all()
    assert [j.params for j in jobs] == [{"from": "2024-01-02"}]  # one request for the whole batch
    assert api.get(f"/api/v1/imports/{batch['id']}").status_code == 409  # no longer a preview


def test_reimporting_the_same_file_adds_zero_rows(
    api: TestClient, account: int, instruments: dict[str, int], db
) -> None:  # type: ignore[no-untyped-def]
    commit_nl(api, account)
    again = preview(api, account)
    dry = accept(api, again["batch"]["id"], again["mapping"])
    assert dry["counts"] == {"new": 0, "duplicate": 7, "error": 0, "skipped": 0}
    assert dry["can_commit"] is False
    r = api.post(f"/api/v1/imports/{again['batch']['id']}/commit", json={})
    assert r.status_code == 422 and "nothing new to import" in r.json()["detail"]
    assert db.query(LedgerTransaction).count() == 7


def test_a_file_with_extra_rows_only_adds_the_new_ones(
    api: TestClient, account: int, instruments: dict[str, int], db
) -> None:  # type: ignore[no-untyped-def]
    commit_nl(api, account)
    text = (FIXTURES / "degiro_transactions_nl.csv").read_text(encoding="utf-8")
    extra = (
        text
        + '28-03-2024,10:00,ISHARES CORE S&P 500 UCITS ETF,IE00B5BMR087,XET,XETR,2,"490,00",EUR,"-980,00",EUR,"-980,00",EUR,,"-1,00",EUR,"-981,00",EUR,ord-0007\n'
    )
    p = preview(api, account, data=extra.encode("utf-8"))
    dry = accept(api, p["batch"]["id"], p["mapping"])
    assert dry["counts"] == {"new": 1, "duplicate": 7, "error": 0, "skipped": 0}
    assert api.post(f"/api/v1/imports/{p['batch']['id']}/commit", json={}).status_code == 200
    assert db.query(LedgerTransaction).count() == 8


def test_undo_removes_the_whole_batch_and_allows_a_clean_reimport(
    api: TestClient,
    account: int,
    instruments: dict[str, int],
    db,  # type: ignore[no-untyped-def]
) -> None:
    batch = commit_nl(api, account)
    assert api.delete(f"/api/v1/imports/{batch['id']}").status_code == 204
    db.expire_all()
    assert db.query(Position).count() == 0
    assert all(t.deleted_at is not None for t in db.scalars(select(LedgerTransaction)))
    assert api.get("/api/v1/transactions").json()["items"] == []
    history = {b["id"]: b for b in api.get("/api/v1/imports").json()}
    assert history[batch["id"]]["status"] == "undone"
    assert db.scalars(select(AuditLog).where(AuditLog.action == "undo")).one().diff["removed"] == 7
    assert api.delete(f"/api/v1/imports/{batch['id']}").status_code == 422  # already undone

    again = commit_nl(api, account)  # an undone import no longer blocks a re-import
    assert again["rows_imported"] == 7
    assert position(db, account, instruments[ASML]).quantity == 3


def test_undo_is_refused_when_later_transactions_depend_on_the_import(
    api: TestClient,
    account: int,
    instruments: dict[str, int],
    db,  # type: ignore[no-untyped-def]
) -> None:
    batch = commit_nl(api, account)
    sell = api.post("/api/v1/transactions", json={"account_id": account, "instrument_id": instruments[ASML],
                    "type": "sell", "trade_date": "2024-04-01", "quantity": "3", "price": "1100"})  # fmt: skip
    assert sell.status_code == 201
    r = api.delete(f"/api/v1/imports/{batch['id']}")
    assert r.status_code == 422 and "Cannot undo this import" in r.json()["detail"]
    assert "only 0 are held" in r.json()["detail"]
    assert (
        db.query(LedgerTransaction).filter(LedgerTransaction.deleted_at.is_(None)).count() == 8
    )  # untouched


def test_discarding_a_preview_deletes_the_batch(api: TestClient, account: int, db) -> None:  # type: ignore[no-untyped-def]
    p = preview(api, account)
    assert api.delete(f"/api/v1/imports/{p['batch']['id']}").status_code == 204
    assert db.query(ImportBatch).count() == 0
    assert api.get(f"/api/v1/imports/{p['batch']['id']}").status_code == 404


def test_a_committed_import_cannot_be_remapped_or_committed_again(
    api: TestClient, account: int, instruments: dict[str, int]
) -> None:
    p = preview(api, account)
    accept(api, p["batch"]["id"], p["mapping"])
    api.post(f"/api/v1/imports/{p['batch']['id']}/commit", json={})
    remap = api.put(f"/api/v1/imports/{p['batch']['id']}/mapping", json={"mapping": p["mapping"]})
    assert remap.status_code == 422 and "already committed" in remap.json()["detail"]
    again = api.post(f"/api/v1/imports/{p['batch']['id']}/commit", json={})
    assert again.status_code == 422 and "already committed" in again.json()["detail"]


# --- errors in the data ---------------------------------------------------------------------


def row_csv(*rows: str) -> bytes:
    header = "Date,Time,ISIN,Quantity,Price,Order\n"
    return (header + "".join(r + "\n" for r in rows)).encode("utf-8")


def plain_mapping(**overrides: Any) -> dict[str, Any]:
    base = {"date_format": "%Y-%m-%d", "decimal_separator": ".", "thousands_separator": "",
            "date_col": 0, "time_col": 1, "isin_col": 2, "quantity_col": 3, "price_col": 4,
            "reference_col": 5, "type_mode": "sign", "default_currency": "EUR"}  # fmt: skip
    return base | overrides


def test_cell_errors_name_the_cell_and_what_was_expected(
    api: TestClient, account: int, instruments: dict[str, int]
) -> None:
    data = row_csv(
        f"31/12/2024,10:00,{SXR8},1,100,a",  # wrong date format
        f"2024-01-02,10:00,{SXR8},one,100,b",  # not a number
        f"2024-01-02,10:00,{SXR8},0,100,c",  # no direction
        f"2024-01-02,10:00,{SXR8},1,100,d",  # fine
        "2024-01-02,10:00,,1,100,e",  # no ISIN
        f"2024-01-02,10:00,{SXR8},1,100,f",  # a repeat of d except for its order reference
    )
    p = preview(api, account, data=data)
    dry = accept(api, p["batch"]["id"], plain_mapping())
    reasons = {r["row"]: r["reason"] for r in dry["rows"] if r["status"] == "error"}
    assert (
        "The date '31/12/2024' does not match the format %Y-%m-%d (for example 2024-12-31)"
        in reasons[2]
    )
    assert "'one' is not a number in the chosen format (for example 1,234.56)" in reasons[3]
    assert "quantity is missing or zero" in reasons[4]
    assert "needs an ISIN" in reasons[6]
    assert dry["counts"] == {"new": 2, "duplicate": 0, "error": 4, "skipped": 0}
    assert dry["can_commit"] is False


def test_an_oversell_in_the_file_is_an_error_row_and_valid_rows_can_still_be_imported(
    api: TestClient,
    account: int,
    instruments: dict[str, int],
    db,  # type: ignore[no-untyped-def]
) -> None:
    data = row_csv(
        f"2024-01-02,10:00,{SXR8},10,100,a",
        f"2024-01-03,10:00,{SXR8},-11,110,b",  # sells more than the 10 held
        f"2024-01-04,10:00,{ASML},1,900,c",
    )
    p = preview(api, account, data=data)
    dry = accept(api, p["batch"]["id"], plain_mapping())
    errors = [r for r in dry["rows"] if r["status"] == "error"]
    assert [r["row"] for r in errors] == [
        3
    ] and "Cannot sell 11 units on 2024-01-03: only 10 are held" in errors[0]["reason"]
    refused = api.post(f"/api/v1/imports/{p['batch']['id']}/commit", json={})
    assert refused.status_code == 422 and db.query(LedgerTransaction).count() == 0
    ok = api.post(f"/api/v1/imports/{p['batch']['id']}/commit", json={"skip_errors": True})
    assert ok.status_code == 200
    batch = ok.json()
    assert (batch["rows_imported"], batch["rows_skipped"]) == (2, 1)
    assert batch["errors"][0]["row"] == 3
    assert position(db, account, instruments[SXR8]).quantity == 10


def test_a_newest_first_export_still_replays_in_the_right_order(
    api: TestClient, account: int, instruments: dict[str, int], db
) -> None:  # type: ignore[no-untyped-def]
    data = row_csv(
        f"2024-02-01,10:00,{SXR8},-5,110,sell",  # listed before the buy it depends on
        f"2024-02-01,09:00,{SXR8},10,100,buy",  # the same day
    )
    p = preview(api, account, data=data)
    dry = accept(api, p["batch"]["id"], plain_mapping())
    assert dry["counts"]["new"] == 2 and dry["counts"]["error"] == 0
    api.post(f"/api/v1/imports/{p['batch']['id']}/commit", json={})
    assert position(db, account, instruments[SXR8]).quantity == 5


# --- type column, encodings, presets --------------------------------------------------------


STATEMENT_MAPPING = {
    "date_format": "%d/%m/%Y", "decimal_separator": ",", "thousands_separator": "",
    "date_col": 0, "type_col": 1, "isin_col": 2, "amount_col": 3, "note_col": 4,
    "type_mode": "column",
    "type_map": {"deposit": "deposit", "dividend": "dividend", "fee": "fee"},
    "skip_types": ["cash sweep"],
}  # fmt: skip


def test_type_column_mapping_with_skipped_and_unmapped_values(
    api: TestClient, account: int, instruments: dict[str, int], db
) -> None:  # type: ignore[no-untyped-def]
    p = preview(api, account, name="account_statement.csv")
    assert (
        p["delimiter"] == ";" and p["mapping"]["type_mode"] == "column"
    )  # a type column was found
    assert (
        p["mapping"]["date_col"] == 0
        and p["mapping"]["isin_col"] == 2
        and p["mapping"]["amount_col"] == 3
    )
    dry = accept(api, p["batch"]["id"], STATEMENT_MAPPING)
    assert dry["counts"] == {"new": 3, "duplicate": 0, "error": 1, "skipped": 1}
    problems = [r["reason"] for r in dry["rows"] if r["status"] == "error"]
    assert problems == ["The type 'mystery' is not mapped to a transaction type."]
    ok = api.post(f"/api/v1/imports/{p['batch']['id']}/commit", json={"skip_errors": True})
    assert ok.status_code == 200 and ok.json()["rows_imported"] == 3
    kinds = sorted((t.type, t.net_amount_eur) for t in db.scalars(select(LedgerTransaction)))
    assert kinds == [("deposit", D("1000.00")), ("dividend", D("4.25")), ("fee", D("2.00"))]
    assert position(db, account, instruments[SXR8]).income_eur == D("4.25")


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "cp1252"])
def test_text_encodings_are_detected(api: TestClient, account: int, encoding: str) -> None:
    text = (FIXTURES / "account_statement.csv").read_text(encoding="utf-8")
    assert "é" in text  # the fixture holds a non-ASCII character
    p = preview(api, account, data=text.encode(encoding))
    assert p["encoding"] == ("utf-8-sig" if encoding == "utf-8-sig" else encoding)
    note = p["sample_rows"][1][4]
    assert note == "Nestlé style accents"  # decoded correctly in every encoding


def test_presets_are_saved_listed_reused_and_deleted(
    api: TestClient, account: int, instruments: dict[str, int]
) -> None:
    p = preview(api, account, name="account_statement.csv")
    accept(api, p["batch"]["id"], STATEMENT_MAPPING, save_as_preset="My statement")
    presets = api.get("/api/v1/import-presets").json()
    assert [(x["name"], x["mapping"]["type_map"]["dividend"]) for x in presets] == [
        ("My statement", "dividend")
    ]
    reused = preview(api, account, name="account_statement.csv", preset_id=presets[0]["id"])
    assert reused["from_preset"] is True and reused["mapping"] == presets[0]["mapping"]
    assert reused["batch"]["preset_id"] == presets[0]["id"]
    dry = api.get(f"/api/v1/imports/{reused['batch']['id']}/dry-run").json()
    assert dry["counts"]["new"] == 3  # the saved mapping works without any manual step

    updated = api.post(
        "/api/v1/import-presets", json={"name": "My statement", "mapping": plain_mapping()}
    )
    assert (
        updated.status_code == 201 and len(api.get("/api/v1/import-presets").json()) == 1
    )  # same name: replaced
    assert api.delete(f"/api/v1/import-presets/{presets[0]['id']}").status_code == 204
    assert api.get("/api/v1/import-presets").json() == []
    assert api.delete(f"/api/v1/import-presets/{presets[0]['id']}").status_code == 404
    blank = api.post("/api/v1/import-presets", json={"name": "   ", "mapping": plain_mapping()})
    assert blank.status_code == 422


def test_import_history_and_dates(
    api: TestClient, account: int, instruments: dict[str, int]
) -> None:
    commit_nl(api, account)
    preview(api, account, name="degiro_transactions_en.csv")
    history = api.get("/api/v1/imports").json()
    assert [(b["file_name"], b["status"]) for b in history] == [
        ("degiro_transactions_en.csv", "preview"), ("degiro_transactions_nl.csv", "committed"),
    ]  # fmt: skip
    assert date.fromisoformat(history[1]["committed_at"][:10])
