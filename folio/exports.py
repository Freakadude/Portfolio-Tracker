"""Exporting the ledger and the positions (FR-TX-13).

The transactions file has exactly the columns `imports.mapping.FOLIO_HEADERS`, so the import
wizard recognises it and reads it back with no choices to make: dates in ISO form, a dot as the
decimal separator, the exchange rate as the multiplier to euro (exact), and the amount column
holding the euro amount of cash and transfer-in rows (the ratio for a split). Only posted
transactions are exported; proposed ones are not part of the ledger yet.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.db.models import Account
from folio.db.models_ledger import Instrument, LedgerTransaction
from folio.imports.mapping import FOLIO_HEADERS
from folio.instruments import primary_listing
from folio.positions import load_positions
from folio.reports import _safe

POSITION_COLUMNS = (
    "account", "instrument", "isin", "ticker", "quantity", "cost_basis_eur", "market_value_eur",
    "unrealized_pnl_eur", "last_close", "currency", "last_close_date",
)  # fmt: skip
_AMOUNT_TYPES = ("dividend", "interest", "fee", "tax", "deposit", "withdrawal", "transfer_in")


def plain(value: Decimal | None) -> str:
    """A number as plain text without exponent or trailing zeros: 330.000000 is 330."""
    return "" if value is None else format(value.normalize(), "f")


_text = plain


def transaction_rows(db: Session, account_id: int | None = None) -> list[dict[str, str]]:
    accounts = {a.id: a.name for a in db.scalars(select(Account))}
    instruments = {i.id: i for i in db.scalars(select(Instrument))}
    query = (
        select(LedgerTransaction)
        .where(LedgerTransaction.deleted_at.is_(None), LedgerTransaction.status == "posted")
        .order_by(LedgerTransaction.trade_date, LedgerTransaction.id)
    )
    if account_id is not None:
        query = query.where(LedgerTransaction.account_id == account_id)
    rows: list[dict[str, str]] = []
    tickers: dict[int, str] = {}
    for tx in db.scalars(query):
        instrument = instruments.get(tx.instrument_id) if tx.instrument_id else None
        if instrument is not None and instrument.id not in tickers:
            listing = primary_listing(db, instrument.id)
            tickers[instrument.id] = listing.ticker if listing else ""
        trade = tx.type in ("buy", "sell", "transfer_in", "transfer_out")
        amount = (
            tx.net_amount_eur
            if tx.type in _AMOUNT_TYPES
            else tx.ratio
            if tx.type == "split"
            else None
        )
        rows.append(
            {
                "date": tx.trade_date.isoformat(),
                "type": tx.type,
                "isin": "" if instrument is None else instrument.isin or "",
                "name": "" if instrument is None else instrument.name,
                "ticker": "" if instrument is None else tickers.get(instrument.id, ""),
                "account": accounts.get(tx.account_id, ""),
                "quantity": _text(tx.quantity) if trade else "",
                "price": _text(tx.price) if trade else "",
                "currency": tx.currency if trade else "",
                "fx_rate_to_eur": _text(tx.fx_rate_to_eur)
                if trade and tx.currency != "EUR"
                else "",
                "fees": _text(tx.fees),
                "fees_currency": tx.fees_currency,
                "taxes": _text(tx.taxes),
                "amount": _text(amount),
                "reference": tx.external_ref or f"folio-{tx.id}",
                "note": tx.note or "",
            }
        )
    return rows


def transactions_csv(rows: list[dict[str, str]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(FOLIO_HEADERS)
    for row in rows:
        writer.writerow(
            [
                _safe(row[h]) if h in ("name", "ticker", "account", "note") else row[h]
                for h in FOLIO_HEADERS
            ]
        )
    return out.getvalue()


def position_rows(db: Session, today: date, account_id: int | None = None) -> list[dict[str, str]]:
    rows, _totals = load_positions(db, account_id=account_id, today=today)
    out: list[dict[str, str]] = []
    for r in rows:
        price, m = r.price, r.metrics
        out.append(
            {
                "account": r.account.name,
                "instrument": r.instrument.name,
                "isin": r.instrument.isin or "",
                "ticker": "" if r.listing is None else r.listing.ticker,
                "quantity": _text(r.state.quantity),
                "cost_basis_eur": _text(r.state.cost_basis_eur),
                "market_value_eur": "" if m is None else _text(m.market_value_eur),
                "unrealized_pnl_eur": "" if m is None else _text(m.unrealized_pnl_eur),
                "last_close": "" if price is None else _text(price.close),
                "currency": "" if r.listing is None else r.listing.currency,
                "last_close_date": "" if price is None else price.date.isoformat(),
            }
        )
    return out


def positions_csv(rows: list[dict[str, str]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(POSITION_COLUMNS)
    for row in rows:
        writer.writerow(
            [
                _safe(row[c]) if c in ("account", "instrument", "ticker") else row[c]
                for c in POSITION_COLUMNS
            ]
        )
    return out.getvalue()


def as_json(kind: str, rows: list[dict[str, str]], exported_on: date) -> str:
    """The same rows as a JSON document with the date it was made."""
    document: dict[str, Any] = {"exported_on": exported_on.isoformat(), kind: rows}
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"
