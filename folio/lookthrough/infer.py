"""Working out the layout of a holdings table from what is in it, not from exact column names
(FR-MD-09).

Issuers name and order their columns differently, in several languages, and new layouts keep
appearing. Three steps, each used only when the one before found nothing:

1. exact names (the lists in `parse.py`, checked first by the caller);
2. keywords inside the header text ("Exposure Country" holds "country");
3. the content: the weights are the column of numbers that adds up to about 100 (or 1); the name
   is the widest column of different texts beside it; an ISIN column is recognised by the shape
   of its cells; the row above the numbers is the header, or a made-up one when there is none.

Nothing is guessed silently: the owner sees the result in the preview and can change any column.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from folio.imports.mapping import CellError, detect_separators, parse_decimal

Table = list[list[str]]

# Words inside a header that say what a column holds (English, German, Dutch, French, Spanish).
KEYWORDS: dict[str, tuple[str, ...]] = {
    "weight": ("weight", "gewicht", "weging", "poids", "pondération", "peso", "% of net"),
    "name": (
        "name", "naam", "nom ", "description", "bezeichnung", "holding", "security", "emittent",
        "titel", "wertpapier", "instrument", "constituent", "company", "nombre",
    ),
    "isin": ("isin",),
    "ticker": ("ticker", "symbol", "tidm", "kürzel", "sedol"),
    "sector": ("sector", "sektor", "branche", "secteur", "industry", "sector"),
    "country": ("country", "land", "standort", "location", "pays", "domicile", "país"),
    "currency": ("currency", "währung", "valuta", "devise", "ccy", "moneda"),
    "kind": ("asset class", "anlageklasse", "security type", "klasse", "type"),
}  # fmt: skip

_NUMBER = re.compile(r"^-?\d[\d.,\s]*%?$|^-?[.,]\d+%?$")
_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")
_CODE = re.compile(r"^[A-Z]{3}$")
_MAX_GAP = 2  # rows without a number that do not end a run (a sub-total line, a blank)
_MIN_RUN = 3


def loose_index(headers: list[str], field: str, taken: set[int] = frozenset()) -> int | None:  # type: ignore[assignment]
    """The first header whose text contains a keyword of `field`, not already used."""
    for index, text in enumerate(headers):
        lowered = text.strip().lower()
        if index in taken or not lowered:
            continue
        if any(word in lowered for word in KEYWORDS[field]):
            return index
    return None


@dataclass(frozen=True)
class Inferred:
    table: Table  # the table, with a made-up header row inserted when the file had none
    header_row: int
    weight: int
    name: int | None
    isin: int | None
    currency: int | None
    made_up_header: bool


def _looks_numeric(cell: str) -> bool:
    return bool(_NUMBER.match(cell.replace(" ", "")))


def _column_values(table: Table, col: int) -> list[tuple[int, Decimal]]:
    """The numeric cells of a column, with their row numbers."""
    cells = [(n, row[col]) for n, row in enumerate(table) if col < len(row) and row[col]]
    texts = [re.sub(r"[%\s]", "", c) for _, c in cells if _looks_numeric(c)]
    if len(texts) < _MIN_RUN:
        return []
    decimal, thousands = detect_separators(texts[:200])
    out: list[tuple[int, Decimal]] = []
    for n, cell in cells:
        if not _looks_numeric(cell):
            continue
        try:
            out.append((n, parse_decimal(re.sub(r"[%\s]", "", cell), decimal, thousands)))
        except CellError:
            continue
    return out


def _runs(values: list[tuple[int, Decimal]]) -> list[list[tuple[int, Decimal]]]:
    runs: list[list[tuple[int, Decimal]]] = []
    for row, value in values:
        if runs and row - runs[-1][-1][0] <= _MAX_GAP + 1:
            runs[-1].append((row, value))
        else:
            runs.append([(row, value)])
    return runs


def _sums_to_a_whole(run: list[tuple[int, Decimal]]) -> bool:
    total = sum((v for _, v in run), Decimal(0))
    if Decimal(95) <= total <= Decimal(105):
        return True
    return Decimal("0.95") <= total <= Decimal("1.05") and all(
        Decimal("-0.01") <= v <= Decimal(1) for _, v in run
    )


def _header_above(table: Table, start: int) -> int | None:
    """The nearest row above the numbers that is mostly text in at least two cells."""
    for row in range(start - 1, max(-1, start - 5), -1):
        cells = [c for c in table[row] if c]
        if len(cells) >= 2 and sum(1 for c in cells if _looks_numeric(c)) * 2 < len(cells):
            return row
    return None


def _text_columns(table: Table, rows: range, skip: set[int]) -> dict[int, list[str]]:
    width = max((len(table[r]) for r in rows), default=0)
    return {
        col: [table[r][col] for r in rows if col < len(table[r]) and table[r][col]]
        for col in range(width)
        if col not in skip
    }


def infer_layout(table: Table) -> Inferred | None:
    """The best weight column and what sits beside it, or None when no column of numbers adds
    up to a whole (a factsheet with only the top ten holdings is then not guessed at)."""
    best: tuple[tuple[int, int, int], int, list[tuple[int, Decimal]]] | None = None
    width = max((len(r) for r in table), default=0)
    for col in range(width):
        for run in _runs(_column_values(table, col)):
            if len(run) < _MIN_RUN or not _sums_to_a_whole(run):
                continue
            above = _header_above(table, run[0][0])
            label = table[above][col] if above is not None and col < len(table[above]) else ""
            weighty = any(w in label.lower() for w in (*KEYWORDS["weight"], "%"))
            score = (int(weighty), len(run), -col)
            if best is None or score > best[0]:
                best = (score, col, run)
    if best is None:
        return None
    _, weight, run = best
    start, end = run[0][0], run[-1][0]
    found_header = _header_above(table, start)
    made_up = found_header is None
    header = start if found_header is None else found_header
    if made_up:
        columns = max(len(r) for r in table)
        table = [*table[:start], [f"(column {i + 1})" for i in range(columns)], *table[start:]]
        start, end = start + 1, end + 1
    rows = range(start, end + 1)
    cols = _text_columns(table, rows, {weight})
    count = len(rows)

    isin = next(
        (
            c
            for c, cells in cols.items()
            if len(cells) >= count * 0.5
            and sum(bool(_ISIN.match(x)) for x in cells) >= len(cells) * 0.7
        ),
        None,
    )
    currency = next(
        (
            c
            for c, cells in cols.items()
            if c != isin
            and len(cells) >= count * 0.8
            and sum(bool(_CODE.match(x)) for x in cells) >= len(cells) * 0.9
            and len(set(cells)) <= 25
        ),
        None,
    )
    name: int | None = None
    longest = 0.0
    for c, cells in cols.items():
        if c in (isin, currency) or len(cells) < count * 0.8:
            continue
        texts = [x for x in cells if not _looks_numeric(x) and not _ISIN.match(x)]
        if len(texts) < len(cells) * 0.9 or len(set(texts)) < len(texts) * 0.9:
            continue
        average = sum(len(x) for x in texts) / len(texts)
        if average > longest:
            name, longest = c, average
    return Inferred(table, header, weight, name, isin, currency, made_up)
