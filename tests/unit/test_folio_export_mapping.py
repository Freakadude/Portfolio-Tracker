"""Folio's own export layout is recognised and read back exactly (FR-TX-13), and a taxes column
is read for any import."""

from decimal import Decimal

from folio.imports.mapping import (
    FOLIO_HEADERS,
    ImportMapping,
    convert_row,
    detect_preset,
    folio_mapping,
    suggest_mapping,
)
from folio.imports.parse import parse_csv

D = Decimal


def test_exactly_the_columns_of_the_export_make_it_a_folio_file() -> None:
    assert detect_preset(list(FOLIO_HEADERS)) == "folio"
    assert detect_preset([h.upper() for h in FOLIO_HEADERS]) == "folio"
    assert detect_preset(list(FOLIO_HEADERS[:-1])) is None  # a column short
    assert detect_preset(list(reversed(FOLIO_HEADERS))) is None  # another order: not ours


def test_the_mapping_needs_no_choices() -> None:
    first = ",".join(["2024-01-02", "buy", "X"] + [""] * (len(FOLIO_HEADERS) - 3))
    parsed = parse_csv((",".join(FOLIO_HEADERS) + "\n" + first + "\n").encode("utf-8"))
    mapping = suggest_mapping(parsed)
    assert mapping == folio_mapping(list(FOLIO_HEADERS))
    assert (mapping.date_format, mapping.decimal_separator, mapping.fx_semantics) == (
        "%Y-%m-%d",
        ".",
        "to_eur",
    )
    assert mapping.type_mode == "column" and mapping.type_map["transfer_in"] == "transfer_in"
    assert [mapping.date_col, mapping.type_col, mapping.taxes_col, mapping.reference_col] == [
        0,
        1,
        12,
        14,
    ]


def row(**cells: str) -> list[str]:
    base = dict.fromkeys(FOLIO_HEADERS, "")
    base.update(cells)
    return [base[h] for h in FOLIO_HEADERS]


def test_a_trade_with_a_rate_fees_and_taxes_is_read_exactly() -> None:
    m = folio_mapping(list(FOLIO_HEADERS))
    r = convert_row(
        1,
        row(date="2024-04-01", type="buy", isin="US0378331005", quantity="7", price="12.3456",
            currency="USD", fx_rate_to_eur="0.9234567", fees="0.55", fees_currency="EUR",
            taxes="0.25", reference="folio-1"),
        m,
        account_id=1,
    )  # fmt: skip
    assert r.status == "ok" and r.tx is not None
    assert (r.tx.fx_rate_to_eur, r.tx.fees, r.tx.taxes) == (D("0.9234567"), D("0.55"), D("0.25"))
    assert (r.tx.quantity, r.tx.price, r.tx.currency) == (D(7), D("12.3456"), "USD")


def test_a_dividend_keeps_its_withholding_and_a_split_its_ratio() -> None:
    m = folio_mapping(list(FOLIO_HEADERS))
    div = convert_row(
        1, row(date="2024-05-01", type="dividend", isin="X", amount="3.21", taxes="0.48"), m, 1
    )
    assert div.tx is not None and (div.tx.net_amount_eur, div.tx.taxes) == (D("3.21"), D("0.48"))
    split = convert_row(2, row(date="2024-05-02", type="split", isin="X", amount="4"), m, 1)
    assert split.tx is not None and split.tx.ratio == D(4)


def test_the_taxes_column_is_found_by_name_in_any_other_file() -> None:
    parsed = parse_csv(b"Date,ISIN,Quantity,Price,Taxes\n2024-01-02,IE00B5BMR087,1,100,0.7\n")
    mapping = suggest_mapping(parsed)
    assert mapping.taxes_col == 4
    assert ImportMapping.model_validate(mapping.model_dump()).taxes_col == 4
    assert ImportMapping().taxes_col is None
