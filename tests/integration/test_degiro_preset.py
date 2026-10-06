"""The Degiro preset (FR-TX-08): an export with the owner's real header row, filled with invented
trades, imports with no manual mapping, and the AutoFX fee is part of the cost basis.

The header is the one of the owner's current Degiro "Transactions" export (columns only, never
data): Date, Time, Product, ISIN, Reference exchange, Venue, Quantity, Price, <currency>, Local
value, <currency>, Value EUR, Exchange rate, AutoFX Fee, Transaction and/or third party fees EUR,
Total EUR, Order ID.
"""

from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient

from folio.imports.mapping import ImportMapping, detect_preset, suggest_mapping
from folio.imports.parse import parse_csv
from folio.marketdata.fx import to_eur_multiplier

# ruff: noqa: F811
from tests.integration.test_imports_api import (  # noqa: F401
    AAPL,
    FIXTURES,
    SXR8,
    account,
    api,
    db,
    instruments,
    position,
    preview,
)

D = Decimal
FILE = "degiro_transactions_2026.csv"
HEADER = (FIXTURES / FILE).read_text(encoding="utf-8").splitlines()[0].split(",")


def test_the_header_row_is_recognised_as_degiro() -> None:
    assert detect_preset(HEADER) == "degiro"
    dutch = [
        "Datum", "Tijd", "Product", "ISIN", "Beurs", "Uitvoeringsplaats", "Aantal", "Koers", "",
        "Lokale waarde", "", "Waarde EUR", "Wisselkoers", "AutoFX kosten",
        "Transactiekosten en/of kosten van derden EUR", "Totaal EUR", "Order ID",
    ]  # fmt: skip
    assert detect_preset(dutch) == "degiro"
    assert detect_preset(["Date", "ISIN", "Quantity", "Price"]) is None
    assert detect_preset([]) is None


def test_the_columns_are_found_without_any_manual_mapping() -> None:
    parsed = parse_csv((FIXTURES / FILE).read_bytes())
    m = suggest_mapping(parsed)
    assert (m.date_col, m.time_col, m.isin_col) == (0, 1, 3)
    assert (m.quantity_col, m.price_col, m.currency_col) == (6, 7, 8)  # the currency is unnamed
    assert (m.fx_col, m.fees_col, m.reference_col) == (12, 14, 16)
    assert m.extra_fee_cols == [13]  # the AutoFX fee
    assert m.amount_col == 15  # "Total EUR", found although the header has a currency
    assert (m.type_mode, m.fx_semantics, m.date_format) == ("sign", "per_eur", "%d-%m-%Y")
    # no thousands mark in quantity or price, but the amounts ("-4,542.90") have one
    assert (m.decimal_separator, m.thousands_separator) == (".", ",")


def test_the_dutch_header_is_mapped_too() -> None:
    text = (
        "Datum,Tijd,Product,ISIN,Beurs,Uitvoeringsplaats,Aantal,Koers,,Lokale waarde,,Waarde EUR,"
        "Wisselkoers,AutoFX kosten,Transactiekosten en/of kosten van derden EUR,Totaal EUR,Order ID\n"
        '02-01-2024,09:15,X,IE00B5BMR087,XET,XETR,10,"454,19",EUR,"-4.541,90",EUR,"-4.541,90",,,"-1,00",'
        '"-4.542,90",ord-1\n'
    )
    m = suggest_mapping(parse_csv(text.encode("utf-8")))
    assert (m.fees_col, m.extra_fee_cols, m.quantity_col, m.price_col) == (14, [13], 6, 7)
    assert m.amount_col == 15  # "Totaal EUR"
    assert (m.decimal_separator, m.thousands_separator) == (",", ".")  # "-4.542,90"


def test_the_upload_says_which_broker_it_recognised(api: TestClient, account: int) -> None:  # noqa: F811
    p = preview(api, account, name=FILE)
    assert p["detected_preset"] == "degiro" and p["from_preset"] is False
    assert p["mapping"]["extra_fee_cols"] == [13]
    other = preview(api, account, name="account_statement.csv")
    assert other["detected_preset"] is None


def test_the_sample_export_imports_with_no_manual_mapping(  # noqa: F811
    api: TestClient, account: int, instruments: dict[str, int], db
) -> None:  # type: ignore[no-untyped-def]
    p = preview(api, account, name=FILE)
    batch = p["batch"]["id"]
    # accept the suggested mapping exactly as it came
    r = api.put(f"/api/v1/imports/{batch}/mapping", json={"mapping": p["mapping"]})
    assert r.status_code == 200, r.text
    dry = r.json()
    assert dry["counts"] == {"new": 4, "duplicate": 0, "error": 0, "skipped": 0}
    assert dry["can_commit"] is True
    done = api.post(f"/api/v1/imports/{batch}/commit", json={})
    assert done.status_code == 200 and done.json()["rows_imported"] == 4

    # the S&P fund: 10 bought with a fee of 1, 4 sold -> 6 left at 6/10 of the cost 4,542.90
    fund = position(db, account, instruments[SXR8])
    assert fund.quantity == 6 and fund.cost_basis_eur == D("4542.90") * 6 / 10  # incl. the fee
    # Apple: 5 bought at 180 USD with the broker's rate 1.0841, a 1.00 fee and a 2.07 AutoFX fee
    one_left = position(db, account, instruments[AAPL])
    assert one_left.quantity == 3
    multiplier = to_eur_multiplier(D("1.0841"))
    cost_of_five = D(900) * multiplier + D("1.00") + D("2.07")  # the AutoFX fee is in the cost
    assert abs(one_left.cost_basis_eur - cost_of_five * 3 / 5) < D("1E-9")


def test_without_the_autofx_column_the_cost_basis_would_be_short(  # noqa: F811
    api: TestClient, account: int, instruments: dict[str, int], db
) -> None:  # type: ignore[no-untyped-def]
    """The reason the extra fee column exists: the broker states cost to the cent."""
    p = preview(api, account, name=FILE)
    mapping: dict[str, Any] = {**p["mapping"], "extra_fee_cols": []}
    batch = p["batch"]["id"]
    api.put(f"/api/v1/imports/{batch}/mapping", json={"mapping": mapping})
    api.post(f"/api/v1/imports/{batch}/commit", json={})
    short = position(db, account, instruments[AAPL])
    full = D(900) * to_eur_multiplier(D("1.0841")) + D("1.00") + D("2.07")
    assert abs(short.cost_basis_eur - (full - D("2.07")) * 3 / 5) < D("1E-9")


def test_the_saved_mapping_keeps_the_extra_fee_columns() -> None:
    mapping = ImportMapping(fees_col=14, extra_fee_cols=[13])
    assert ImportMapping.model_validate(mapping.model_dump()).extra_fee_cols == [13]
    assert ImportMapping().extra_fee_cols == []
