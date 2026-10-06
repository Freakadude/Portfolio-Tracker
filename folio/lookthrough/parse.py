"""Reading an ETF issuer's holdings file (FR-MD-09).

Issuers publish holdings as CSV, but not alike: iShares puts about nine lines of fund details
above the table and a legal footer below it, VanEck and HANetf start straight at the header, and
column names differ ("Weight (%)", "% of net assets", "Weighting"). The header row is found by
its column names, the columns are matched by those names, and the owner can correct the match on
a preview. Cash and derivative lines are left out; their weight shows up as "other holdings".
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from folio.imports.mapping import CellError, detect_separators, parse_decimal
from folio.imports.parse import ParseError, decode, sniff_delimiter
from folio.lookthrough.formats import (
    HOLDINGS_MAX_BYTES,
    Table,
    detect_kind,
    read_pdf,
    read_workbook,
)

_NAME = (
    "name",
    "security name",
    "holding",
    "holdings",
    "holding name",
    "constituent",
    "company",
    "security",
    "instrument",
    "issuer",
    "description",
    "naam",
)
_WEIGHT = (
    "weight (%)",
    "weight",
    "weight %",
    "% weight",
    "weighting",
    "weighting (%)",
    "% of net assets",
    "% of fund",
    "% of total",
    "% of market value",
    "% of nav",
    "portfolio weight",
    "market weight",
    "gewicht",
    "gewicht %",
    "gewicht (%)",
    "gewichtung",
    "gewichtung %",
    "gewichtung (%)",
)
_ISIN = ("isin",)
_TICKER = ("ticker", "symbol", "ticker symbol", "issuer ticker", "emittententicker")
_SECTOR = ("sector", "gics sector", "sector classification", "industry", "sektor", "branche")
_COUNTRY = (
    "location",
    "country",
    "country of risk",
    "country of domicile",
    "land",
    "standort",
)
_CURRENCY = (
    "currency",
    "market currency",
    "base currency",
    "trading currency",
    "valuta",
    "marktwährung",
    "währung",
)
_KIND = ("asset class", "security type", "type", "anlageklasse")
_NOT_A_COMPANY = (
    "cash",
    "derivative",
    "future",
    "fx",
    "money market",
    "forward",
    "swap",
    "collateral",
    "margin",
    "other",
    "liquidity",
    "geldmarkt",
    "barmittel",
    "derivat",
    "termin",
)
# a sector column that says the line is cash or derivatives ("other" can be a real sector)
_NOT_A_COMPANY_SECTOR = ("cash and/or derivatives", "barmittel", "derivat", "liquidity")
_AS_OF = re.compile(r"as of|as at|holdings date|peildatum|\bstand\b|\bper\b", re.IGNORECASE)
_DATE_FORMATS = (
    "%b %d, %Y",
    "%d-%b-%Y",
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d.%m.%Y",
    "%B %d, %Y",
    "%d %b %Y",
)
_ISIN_SHAPE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")
_DATE_TEXT = re.compile(
    r"\d{1,2}[./-]\w{2,3}[./-]\d{4}|[A-Za-z]+ \d{1,2}, \d{4}|\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}[./]\d{1,2}[./]\d{4}|\d{1,2}[. ]+[^\W\d_]{3,9}[. ]*\d{4}"
)
# month names as written in English, German, Dutch and French (by their first three letters)
_MONTHS = {
    "jan": 1, "feb": 2, "fév": 2, "mar": 3, "mär": 3, "mrt": 3, "apr": 4, "avr": 4,
    "mai": 5, "may": 5, "mei": 5, "jun": 6, "jui": 6, "jul": 7, "aug": 8, "aoû": 8,
    "sep": 9, "okt": 10, "oct": 10, "nov": 11, "dez": 12, "dec": 12, "déc": 12,
}  # fmt: skip
_DAY_MONTH_YEAR = re.compile(r"(\d{1,2})[. ]+([^\W\d_]{3,9})[. ]*(\d{4})")
HEADER_SEARCH_ROWS = 60


class HoldingsMapping(BaseModel):
    """Which column holds what, by position. `header_row` is the 0-based index of the header
    among the file's non-blank rows."""

    header_row: int = 0
    sheet: str | None = None  # the workbook sheet; None for a CSV
    name: int | None = None
    weight: int | None = None
    isin: int | None = None
    ticker: int | None = None
    sector: int | None = None
    country: int | None = None
    currency: int | None = None
    kind: int | None = None
    weight_is_fraction: bool = False  # 0.0712 instead of 7.12 (%)
    decimal_separator: Literal[".", ","] = "."
    thousands_separator: Literal["", ".", ",", " "] = ""


@dataclass(frozen=True)
class Constituent:
    name: str
    weight_pct: Decimal
    isin: str | None = None
    ticker: str | None = None
    sector: str | None = None
    country: str | None = None
    currency: str | None = None


@dataclass(frozen=True)
class SheetInfo:
    name: str
    holdings: int  # rows below its header with a weight; 0 when it has no holdings table


@dataclass(frozen=True)
class HoldingsFile:
    table: list[list[str]]  # every non-blank row of the file (of the chosen sheet)
    headers: list[str]
    mapping: HoldingsMapping
    as_of: date | None  # the date the file states, if it does
    sheets: list[SheetInfo] = field(default_factory=list)  # more than one for a workbook


@dataclass
class HoldingsRead:
    constituents: list[Constituent]
    covered_pct: Decimal
    dropped: list[str] = field(default_factory=list)  # lines left out (cash, derivatives)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _index(headers: list[str], names: tuple[str, ...]) -> int | None:
    lowered = [h.strip().lower() for h in headers]
    for name in names:
        if name in lowered:
            return lowered.index(name)
    return None


def _csv_table(data: bytes) -> Table:
    text, _ = decode(data)
    delimiter = sniff_delimiter(_first_table_line(text))
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
    return [[c.strip() for c in row] for row in rows if any(c.strip() for c in row)]


def _without_repeated_headers(table: Table) -> Table:
    """A table that goes over several pages repeats its header on each of them."""
    header = find_header(table)
    if header is None:
        return table
    row = table[header]
    return table[: header + 1] + [r for r in table[header + 1 :] if r != row]


def _read_tables(data: bytes) -> dict[str, Table]:
    """The tables of a file: one for a CSV (named ""), one per visible sheet for a workbook."""
    if not data.strip():
        raise ParseError("The file is empty.")
    if len(data) > HOLDINGS_MAX_BYTES:
        raise ParseError("The file is larger than 10 MB.")
    kind = detect_kind(data)
    if kind == "xlsx":
        return read_workbook(data)
    if kind == "xls":
        raise ParseError(
            "That is an old Excel file (.xls). Open it in Excel and save it as .xlsx or as CSV, "
            "then upload that."
        )
    if kind == "pdf":
        return {"": _without_repeated_headers(read_pdf(data))}
    return {"": _csv_table(data)}


def _first_table_line(text: str) -> str:
    """The delimiter is sniffed from the widest of the first lines, since a preamble line such
    as 'Fund Holdings as of,"Oct 03, 2026"' has fewer separators than the header does."""
    lines = [line for line in text.splitlines() if line.strip()][:HEADER_SEARCH_ROWS]
    return max(lines, key=lambda line: max(line.count(d) for d in (",", ";", "\t")), default="")


def find_header(table: list[list[str]]) -> int | None:
    """The first row, among the first sixty, that has both a name and a weight column."""
    for n, row in enumerate(table[:HEADER_SEARCH_ROWS]):
        if _index(row, _WEIGHT) is not None and _index(row, _NAME) is not None:
            return n
    return None


def _stated_date(preamble: list[list[str]]) -> date | None:
    for row in preamble:
        for n, cell in enumerate(row):
            if not _AS_OF.search(cell):
                continue
            candidates = [cell, *row[n + 1 :]]
            for text in candidates:
                found = _DATE_TEXT.search(text)
                if not found:
                    continue
                for fmt in _DATE_FORMATS:
                    try:
                        return datetime.strptime(found.group(0), fmt).date()
                    except ValueError:
                        continue
                written = _DAY_MONTH_YEAR.fullmatch(found.group(0).strip())
                if written and written.group(2).lower()[:3] in _MONTHS:
                    try:
                        return date(
                            int(written.group(3)),
                            _MONTHS[written.group(2).lower()[:3]],
                            int(written.group(1)),
                        )
                    except ValueError:
                        continue
    return None


def _holdings_below(table: Table, header_row: int) -> int:
    """How many rows under the header look like holdings: a weight that is a number."""
    headers = table[header_row]
    weight = _index(headers, _WEIGHT)
    if weight is None:
        return 0
    count = 0
    for row in table[header_row + 1 :]:
        if weight < len(row) and re.fullmatch(r"-?[\d.,\s]+%?", row[weight].replace(" ", "")):
            count += 1
    return count


def suggest(data: bytes, sheet: str | None = None) -> HoldingsFile:
    """Find the header and match the columns by name. For a workbook the sheet with the most
    holdings is taken unless `sheet` names one. Raises ParseError, in words for the owner, when
    the file does not look like a holdings table."""
    tables = _read_tables(data)
    info: list[SheetInfo] = []
    headers_at: dict[str, int | None] = {}
    for name, table in tables.items():
        found = find_header(table)
        headers_at[name] = found
        info.append(SheetInfo(name, 0 if found is None else _holdings_below(table, found)))
    if sheet is not None and sheet not in tables:
        raise ParseError(f"The workbook has no sheet called {sheet!r}.")
    chosen = sheet or max(info, key=lambda i: i.holdings).name
    table, header_row = tables[chosen], headers_at[chosen]
    if header_row is None:
        raise ParseError(
            "No header row with a name column and a weight column was found"
            + (" on any sheet" if len(tables) > 1 and sheet is None else "")
            + ". Open the file in a spreadsheet and check it lists the fund's holdings with "
            "their weight."
        )
    headers = table[header_row]
    body = table[header_row + 1 :]
    weight = _index(headers, _WEIGHT)
    samples = [r[weight] for r in body[:50] if weight is not None and weight < len(r) and r[weight]]
    cleaned = [re.sub(r"[%\s]", "", s) for s in samples]
    decimal, thousands = detect_separators(cleaned)
    values = []
    for s in cleaned:
        try:
            values.append(parse_decimal(s, decimal, thousands))
        except CellError:
            continue
    mapping = HoldingsMapping(
        header_row=header_row,
        sheet=chosen or None,
        name=_index(headers, _NAME),
        weight=weight,
        isin=_index(headers, _ISIN),
        ticker=_index(headers, _TICKER),
        sector=_index(headers, _SECTOR),
        country=_index(headers, _COUNTRY),
        currency=_index(headers, _CURRENCY),
        kind=_index(headers, _KIND),
        weight_is_fraction=bool(values) and Decimal("0.9") <= sum(values) <= Decimal("1.1"),
        decimal_separator=decimal,
        thousands_separator=thousands,
    )
    return HoldingsFile(
        table,
        headers,
        mapping,
        _stated_date(table[:header_row]),
        info if len(tables) > 1 else [],
    )


def _cell(row: list[str], col: int | None) -> str:
    return row[col] if col is not None and col < len(row) else ""


def _text(row: list[str], col: int | None) -> str | None:
    value = _cell(row, col)
    return value if value and value != "-" else None


def read_holdings(file: HoldingsFile, mapping: HoldingsMapping | None = None) -> HoldingsRead:
    """Turn the table into constituents with the given (or the suggested) mapping."""
    m = mapping or file.mapping
    result = HoldingsRead(constituents=[], covered_pct=Decimal(0))
    if m.weight is None or m.name is None:
        result.errors.append(
            "Choose the column with the holding's name and the one with its weight."
        )
        return result
    body = file.table[m.header_row + 1 :]
    unreadable = 0
    for row in body:
        if sum(1 for c in row if c) < 3 and not _cell(row, m.weight):
            continue  # a footer or a stray note
        raw = re.sub(r"[%\s]", "", _cell(row, m.weight))
        if raw in ("", "-"):
            continue
        try:
            weight = parse_decimal(raw, m.decimal_separator, m.thousands_separator)
        except CellError:
            unreadable += 1
            continue
        if m.weight_is_fraction:
            weight *= 100
        name = _cell(row, m.name)
        kind = _cell(row, m.kind).lower()
        sector_text = _cell(row, m.sector).lower()
        if (
            any(word in kind for word in _NOT_A_COMPANY)
            or any(word in sector_text for word in _NOT_A_COMPANY_SECTOR)
            or (not _cell(row, m.isin) and any(word == name.lower() for word in _NOT_A_COMPANY))
        ):
            result.dropped.append(f"{name or kind}: {weight.normalize():f} %")
            continue
        isin = _cell(row, m.isin).upper()
        currency = _cell(row, m.currency).upper()
        result.constituents.append(
            Constituent(
                name=name or isin or "(no name)",
                weight_pct=weight,
                isin=isin if _ISIN_SHAPE.match(isin) else None,
                ticker=_text(row, m.ticker),
                sector=_text(row, m.sector),
                country=_text(row, m.country),
                currency=currency if re.fullmatch(r"[A-Z]{3}", currency) else None,
            )
        )
    result.covered_pct = sum((c.weight_pct for c in result.constituents), Decimal(0))
    if unreadable:
        result.warnings.append(f"{unreadable} line(s) had a weight that could not be read.")
    if not result.constituents:
        result.errors.append("No holdings were found below the header.")
    elif result.covered_pct > Decimal("105"):
        result.errors.append(
            f"The weights add up to {result.covered_pct:.1f} %. Check whether the weight column "
            "holds percentages or fractions."
        )
    elif result.covered_pct < Decimal("98"):
        result.warnings.append(
            f"The file covers {result.covered_pct:.1f} % of the fund; the rest is shown as "
            "other holdings."
        )
    return result
