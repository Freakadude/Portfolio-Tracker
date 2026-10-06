"""Reading issuers' holdings files (FR-MD-09): the header sits below a preamble, columns are
matched by name, cash and derivatives are left out, and number formats vary."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from folio.imports.parse import ParseError
from folio.lookthrough.parse import HoldingsMapping, read_holdings, suggest

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "lookthrough"


def load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_an_ishares_style_file_is_read_below_its_preamble_and_above_its_footer() -> None:
    file = suggest(load("ishares_style.csv"))
    assert file.table[file.mapping.header_row][1] == "Name"
    assert file.as_of == date(2026, 10, 3)  # the file states its own date, not "Inception Date"
    read = read_holdings(file)
    assert [(c.ticker, c.weight_pct) for c in read.constituents] == [
        ("AAA", Decimal("40.00")),
        ("BBB", Decimal("30.50")),
        ("CCC", Decimal("29.00")),
    ]
    first = read.constituents[0]
    assert (first.name, first.sector, first.country, first.currency) == (
        "ALPHA TECH INC",
        "Information Technology",
        "United States",
        "USD",
    )
    assert read.covered_pct == Decimal("99.50")
    assert [d.split(":")[0] for d in read.dropped] == ["USD CASH", "FUTURES USD"]
    assert read.errors == []


def test_a_semicolon_file_with_comma_decimals_and_percent_signs() -> None:
    file = suggest(load("generic_semicolon.csv"))
    assert (file.mapping.decimal_separator, file.mapping.weight_is_fraction) == (",", False)
    read = read_holdings(file)
    assert [(c.isin, c.weight_pct) for c in read.constituents] == [
        ("NL0000000001", Decimal("12.5")),
        ("US0000000002", Decimal("7.25")),
        ("FR0000000003", Decimal("3.10")),
    ]
    assert read.constituents[0].country == "Nederland"
    assert any("covers 22.8 %" in w for w in read.warnings)  # a top-N file says so


def test_weights_written_as_fractions_are_noticed_and_scaled() -> None:
    data = b"Name,Weight\nAlpha,0.6\nBeta,0.4\n"
    file = suggest(data)
    assert file.mapping.weight_is_fraction is True
    read = read_holdings(file)
    assert [c.weight_pct for c in read.constituents] == [Decimal("60.0"), Decimal("40.0")]


def test_weights_far_above_one_hundred_are_refused_with_a_hint() -> None:
    read = read_holdings(suggest(b"Name,Weight\nAlpha,80\nBeta,70\n"))
    assert read.errors and "add up to 150.0 %" in read.errors[0]


def test_a_file_without_a_weight_column_is_explained() -> None:
    with pytest.raises(ParseError, match="column of weights that adds up to 100"):
        suggest(b"Name,Amount\nAlpha,1\n")


def test_the_owner_can_correct_the_column_match() -> None:
    file = suggest(b"Name,Weight,Share\nAlpha,10,60\nBeta,20,40\n")
    mapping = file.mapping.model_copy(update={"weight": 2})
    read = read_holdings(file, mapping)
    assert [c.weight_pct for c in read.constituents] == [Decimal("60"), Decimal("40")]
    missing = read_holdings(file, HoldingsMapping(header_row=0, name=None, weight=None))
    assert missing.errors and "Choose the column" in missing.errors[0]
