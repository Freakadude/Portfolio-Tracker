"""Turning CSV rows into transactions: the saved column mapping, auto-detection from the headers,
number and date parsing (comma decimals are common in Dutch exports), and per-row conversion."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from folio.imports.parse import ParsedFile
from folio.ledger_service import TransactionIn
from folio.marketdata.fx import to_eur_multiplier

VALID_TYPES = {
    "buy", "sell", "dividend", "interest", "fee", "tax", "split",
    "transfer_in", "transfer_out", "deposit", "withdrawal",
}  # fmt: skip
_CASH_TYPES = {"dividend", "interest", "fee", "tax", "deposit", "withdrawal"}
_DATE_FORMATS = ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%m/%d/%Y", "%d-%m-%y")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_CURRENCY_SUFFIX = re.compile(r"\s+[a-z]{3}$")  # a header like "total eur"

_ALIASES: dict[str, tuple[str, ...]] = {
    "date_col": ("date", "datum", "trade date", "transaction date", "booking date", "tradedate"),
    "time_col": ("time", "tijd"),
    "isin_col": ("isin",),
    "type_col": ("type", "transaction type", "side", "action", "buy/sell", "soort"),
    "quantity_col": ("quantity", "aantal", "shares", "units", "qty", "number"),
    "price_col": ("price", "koers", "unit price", "share price"),
    "currency_col": ("currency", "valuta"),
    "fx_col": ("exchange rate", "wisselkoers", "fx rate", "fx"),
    "fees_col": (
        "fees",
        "fee",
        "commission",
        "costs",
        "transaction and/or third party fees",
        "transactiekosten en/of kosten van derden",
        "transactiekosten",
    ),  # fmt: skip
    "amount_col": ("amount", "net amount", "total", "totaal", "mutatie", "value"),
    "taxes_col": ("taxes",),
    "reference_col": ("order id", "order-id", "orderid", "reference", "id", "order number"),
    "note_col": ("note", "notes", "description", "omschrijving", "product", "name"),
}


class ImportMapping(BaseModel):
    """Everything needed to read one export layout; saved as a preset (FR-TX-07)."""

    model_config = ConfigDict(extra="forbid")

    date_format: str = "%d-%m-%Y"
    decimal_separator: Literal[",", "."] = "."
    thousands_separator: Literal["", ".", ",", " "] = ""
    date_col: int | None = None
    time_col: int | None = None
    isin_col: int | None = None
    type_col: int | None = None
    quantity_col: int | None = None
    price_col: int | None = None
    currency_col: int | None = None
    fx_col: int | None = None
    fees_col: int | None = None
    # More columns added to the fees, in the fees' currency (for example Degiro's AutoFX fee)
    extra_fee_cols: list[int] = Field(default_factory=list)
    fees_currency_col: int | None = None
    taxes_col: int | None = None  # taxes paid on the trade, or withheld on income, in euro
    amount_col: int | None = None
    reference_col: int | None = None
    note_col: int | None = None
    type_mode: Literal["sign", "column"] = "sign"  # buy/sell from the quantity's sign, or a column
    type_map: dict[str, str] = Field(default_factory=dict)  # text in the file -> transaction type
    skip_types: list[str] = Field(default_factory=list)  # texts whose rows are ignored
    default_currency: str | None = None
    # Degiro and others state the rate as foreign units per euro; others give the multiplier.
    fx_semantics: Literal["per_eur", "to_eur"] = "per_eur"


# --- number and date parsing -------------------------------------------------------------------


class CellError(ValueError):
    """One cell cannot be read; the message names the cell's content and what was expected."""


def parse_decimal(text: str, decimal_separator: str, thousands_separator: str) -> Decimal:
    raw = text.strip()
    negative = raw.startswith("(") and raw.endswith(")")
    cleaned = raw.strip("()").replace(" ", " ")
    if thousands_separator:
        cleaned = cleaned.replace(thousands_separator, "")
    cleaned = cleaned.replace(" ", "")
    if decimal_separator != ".":
        cleaned = cleaned.replace(decimal_separator, ".")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        example = "1.234,56" if decimal_separator == "," else "1,234.56"
        raise CellError(
            f"{text!r} is not a number in the chosen format (for example {example})."
        ) from None
    if not value.is_finite():
        raise CellError(f"{text!r} is not a usable number.")
    return -value if negative else value


def parse_date(text: str, fmt: str) -> date:
    try:
        return datetime.strptime(text.strip(), fmt).date()
    except ValueError:
        example = datetime(2024, 12, 31).strftime(fmt)
        raise CellError(
            f"The date {text!r} does not match the format {fmt} (for example {example})."
        ) from None


# --- auto-detection ----------------------------------------------------------------------------


def _first(rows: list[list[str]], col: int | None, limit: int = 50) -> list[str]:
    if col is None:
        return []
    return [r[col] for r in rows[:limit] if col < len(r) and r[col]]


def detect_date_format(samples: list[str]) -> str | None:
    for fmt in _DATE_FORMATS:
        try:
            for sample in samples:
                datetime.strptime(sample, fmt)
        except ValueError:
            continue
        if samples:
            return fmt
    return None


_COMMA_DECIMAL = re.compile(r"^-?\d{1,3}(\.\d{3})*,\d+$|^-?\d+,\d+$")
_DOT_DECIMAL = re.compile(r"^-?\d{1,3}(,\d{3})*\.\d+$|^-?\d+\.\d+$")


def detect_separators(samples: list[str]) -> tuple[str, str]:
    """(decimal, thousands) from number-like cells; comma decimals win ties (Dutch exports)."""
    comma = sum(1 for s in samples if _COMMA_DECIMAL.match(s))
    dot = sum(1 for s in samples if _DOT_DECIMAL.match(s))
    if comma >= dot and comma > 0:
        thousands = "." if any("." in s and "," in s for s in samples) else ""
        return ",", thousands
    thousands = "," if any("," in s and "." in s for s in samples) else ""
    return ".", thousands


_DEGIRO_EXCHANGE = ("reference exchange", "referentie beurs", "beurs")
_DEGIRO_VENUE = ("venue", "uitvoeringsplaats", "plaats van uitvoering")
_DEGIRO_ORDER = ("order id", "order-id")


def detect_preset(headers: list[str]) -> str | None:
    """The broker an export comes from, when its header row says so (FR-TX-08). Only the
    column names are looked at, in English or Dutch."""
    lowered = {h.strip().lower() for h in headers}
    if tuple(h.strip().lower() for h in headers) == FOLIO_HEADERS:
        return "folio"
    if (
        "isin" in lowered
        and lowered.intersection(_DEGIRO_EXCHANGE)
        and lowered.intersection(_DEGIRO_VENUE)
        and lowered.intersection(_DEGIRO_ORDER)
    ):
        return "degiro"
    return None


# The columns Folio's own export writes (folio/exports.py). An export is recognised by exactly
# these headers, so it reads back without any choices to make (FR-TX-13).
FOLIO_HEADERS = (
    "date", "type", "isin", "name", "ticker", "account", "quantity", "price", "currency",
    "fx_rate_to_eur", "fees", "fees_currency", "taxes", "amount", "reference", "note",
)  # fmt: skip


def folio_mapping(headers: list[str]) -> ImportMapping:
    """The mapping for a file Folio exported: ISO dates, a dot as decimal separator, the type
    spelled as Folio spells it, and the exchange rate as a multiplier to euro (exact)."""
    col = {h.strip().lower(): i for i, h in enumerate(headers)}
    return ImportMapping(
        date_format="%Y-%m-%d",
        decimal_separator=".",
        thousands_separator="",
        date_col=col["date"],
        isin_col=col["isin"],
        type_col=col["type"],
        quantity_col=col["quantity"],
        price_col=col["price"],
        currency_col=col["currency"],
        fx_col=col["fx_rate_to_eur"],
        fees_col=col["fees"],
        fees_currency_col=col["fees_currency"],
        taxes_col=col["taxes"],
        amount_col=col["amount"],
        reference_col=col["reference"],
        note_col=col["note"],
        type_mode="column",
        type_map={t: t for t in sorted(VALID_TYPES)},
        fx_semantics="to_eur",
    )


def _is_fee_header(header: str) -> bool:
    """Degiro's fee column: "Transaction and/or third party fees EUR" and its Dutch form."""
    return header.startswith(("transaction and/or third party fees", "transactiekosten"))


def suggest_mapping(parsed: ParsedFile) -> ImportMapping:
    """A first guess from the header names and the data; the owner confirms or corrects it."""
    if detect_preset(parsed.headers) == "folio":
        return folio_mapping(parsed.headers)
    lowered = [h.strip().lower() for h in parsed.headers]
    found: dict[str, int] = {}
    for field, names in _ALIASES.items():
        if field == "amount_col":
            # "Total EUR" is the amount, and "Total" beats "Value" when an export has both
            plain = [_CURRENCY_SUFFIX.sub("", h) for h in lowered]
            for name in names:
                index = next((i for i, h in enumerate(plain) if h == name), None)
                if index is not None and index not in found.values():
                    found[field] = index
                    break
            continue
        for index, header in enumerate(lowered):
            if header in names and index not in found.values():
                found[field] = index
                break

    def unnamed_currency_after(col: int | None) -> int | None:
        """Exports like Degiro's put the currency in an unnamed column after the amount."""
        if col is None or col + 1 >= len(parsed.headers) or parsed.headers[col + 1].strip():
            return None
        cells = _first(parsed.rows, col + 1)
        return col + 1 if cells and all(_CURRENCY.match(c) for c in cells) else None

    if "fees_col" not in found:
        for index, header in enumerate(lowered):
            if _is_fee_header(header) and index not in found.values():
                found["fees_col"] = index
                break
    extra_fees = [
        index
        for index, header in enumerate(lowered)
        if "autofx" in header and index not in found.values()
    ]

    if "quantity_col" not in found and "type_col" not in found:
        taken = {col for field, col in found.items() if field != "note_col"}
        for index, header in enumerate(lowered):  # an account statement: no trades, only events
            if header in ("description", "omschrijving") and index not in taken:
                found["type_col"] = index
                if found.get("note_col") == index:  # it was guessed to be the note; it is the type
                    del found["note_col"]
                break

    if "currency_col" not in found:
        guess = unnamed_currency_after(found.get("price_col"))
        if guess is not None:
            found["currency_col"] = guess
    fees_currency = unnamed_currency_after(found.get("fees_col"))
    if fees_currency is not None:
        found["fees_currency_col"] = fees_currency

    numbers = (
        _first(parsed.rows, found.get("quantity_col"))
        + _first(parsed.rows, found.get("price_col"))
        + _first(parsed.rows, found.get("amount_col"))  # large amounts show the thousands mark
    )
    decimal_sep, thousands = detect_separators(numbers)
    dates = _first(parsed.rows, found.get("date_col"))
    fmt = detect_date_format(dates) or "%d-%m-%Y"
    mode = "column" if "type_col" in found else "sign"
    return ImportMapping(
        date_format=fmt,
        decimal_separator=decimal_sep,
        thousands_separator=thousands,
        type_mode=mode,
        extra_fee_cols=extra_fees,
        **found,
    )


# --- converting a row --------------------------------------------------------------------------


@dataclass(frozen=True)
class ConvertedRow:
    row_number: int
    status: Literal["ok", "skipped", "error"]
    reason: str | None = None
    tx: TransactionIn | None = None
    isin: str | None = None
    ref: str | None = None  # idempotency key for this row
    summary: dict[str, str] | None = None  # what the owner sees in the preview


def _cell(cells: list[str], col: int | None) -> str:
    return cells[col].strip() if col is not None and col < len(cells) else ""


def _error(number: int, reason: str, isin: str | None = None) -> ConvertedRow:
    return ConvertedRow(number, "error", reason, isin=isin)


def _ref(mapping: ImportMapping, cells: list[str]) -> str:
    """Stable per row: order id, date, time, ISIN, quantity, price, amount. The same fill
    twice in one file gets a counter later, so re-importing a file adds nothing."""
    parts = [
        _cell(cells, mapping.reference_col),
        _cell(cells, mapping.date_col),
        _cell(cells, mapping.time_col),
        _cell(cells, mapping.isin_col).upper(),
        _cell(cells, mapping.quantity_col),
        _cell(cells, mapping.price_col),
        _cell(cells, mapping.amount_col),
        _cell(cells, mapping.type_col).lower(),
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:32]  # noqa: S324


def convert_row(
    number: int, cells: list[str], mapping: ImportMapping, account_id: int
) -> ConvertedRow:
    dec, thou = mapping.decimal_separator, mapping.thousands_separator
    isin = _cell(cells, mapping.isin_col).upper() or None
    try:
        if mapping.date_col is None:
            return _error(number, "No date column is mapped.", isin)
        trade_date = parse_date(_cell(cells, mapping.date_col), mapping.date_format)

        text_type = _cell(cells, mapping.type_col).lower()
        if text_type and text_type in {s.lower() for s in mapping.skip_types}:
            return ConvertedRow(number, "skipped", f"Skipped by rule: {text_type!r}.", isin=isin)

        quantity: Decimal | None = None
        if _cell(cells, mapping.quantity_col):
            quantity = parse_decimal(_cell(cells, mapping.quantity_col), dec, thou)

        if mapping.type_mode == "sign":
            if quantity is None or quantity == 0:
                return _error(
                    number, "The quantity is missing or zero, so buy or sell is unknown.", isin
                )
            kind = "buy" if quantity > 0 else "sell"
        else:
            kind = mapping.type_map.get(text_type, "")
            if kind not in VALID_TYPES:
                shown = text_type or "(empty)"
                return _error(
                    number, f"The type {shown!r} is not mapped to a transaction type.", isin
                )

        price: Decimal | None = None
        if _cell(cells, mapping.price_col):
            price = abs(parse_decimal(_cell(cells, mapping.price_col), dec, thou))
        amount: Decimal | None = None
        if _cell(cells, mapping.amount_col):
            amount = abs(parse_decimal(_cell(cells, mapping.amount_col), dec, thou))
        fees = Decimal(0)
        if _cell(cells, mapping.fees_col):
            fees = abs(parse_decimal(_cell(cells, mapping.fees_col), dec, thou))
        for extra in mapping.extra_fee_cols:
            if _cell(cells, extra):
                fees += abs(parse_decimal(_cell(cells, extra), dec, thou))

        taxes = Decimal(0)
        if _cell(cells, mapping.taxes_col):
            taxes = abs(parse_decimal(_cell(cells, mapping.taxes_col), dec, thou))
        currency = _cell(cells, mapping.currency_col).upper() or (mapping.default_currency or "")
        if currency and not _CURRENCY.match(currency):
            return _error(number, f"{currency!r} is not a three-letter currency code.", isin)
        fees_currency = _cell(cells, mapping.fees_currency_col).upper() or "EUR"

        fx_rate: Decimal | None = None
        if _cell(cells, mapping.fx_col) and currency not in ("", "EUR"):
            raw = parse_decimal(_cell(cells, mapping.fx_col), dec, thou)
            if raw > 0:
                fx_rate = to_eur_multiplier(raw) if mapping.fx_semantics == "per_eur" else raw

        body: dict[str, object] = {
            "account_id": account_id,
            "type": kind,
            "trade_date": trade_date,
            "fees": fees,
            "fees_currency": fees_currency,
            "taxes": taxes,
            "note": _cell(cells, mapping.note_col) or None,
        }
        if kind in ("buy", "sell", "transfer_in", "transfer_out"):
            body.update(
                quantity=abs(quantity) if quantity is not None else None,
                price=price if price is not None else Decimal(0),
                currency=currency or None,
                fx_rate_to_eur=fx_rate,
            )
        if kind in _CASH_TYPES or kind == "transfer_in":
            body["net_amount_eur"] = amount
        if kind == "split":
            body["ratio"] = amount if amount is not None else None
        tx = TransactionIn.model_validate(body)
    except CellError as exc:
        return _error(number, str(exc), isin)
    except ValidationError as exc:
        reason = "; ".join(str(e["msg"]) for e in exc.errors(include_url=False))
        return _error(number, reason, isin)
    uses_amount = kind in _CASH_TYPES or kind in ("transfer_in", "split")
    summary = {
        "date": trade_date.isoformat(),
        "type": kind,
        "isin": isin or "",
        "quantity": str(abs(quantity)) if quantity is not None else "",
        "price": str(price) if price is not None else "",
        "currency": currency,
        "amount_eur": str(amount) if amount is not None and uses_amount else "",
        "fees": str(fees),
    }
    return ConvertedRow(number, "ok", tx=tx, isin=isin, ref=_ref(mapping, cells), summary=summary)
