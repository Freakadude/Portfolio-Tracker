"""Realized result and income per calendar year (FR-TX-12) and the broker reconciliation
(FR-TX-10).

Realized results are read from the lot matches, which already explain every number: the sale's
date puts a match in a year, and its proceeds less its cost is the result. Income is read from
the dividend and interest transactions of the year.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.db.models import Account
from folio.db.models_ledger import Instrument, LedgerTransaction, LotMatch
from folio.ledger_service import compute_state, to_txin

ZERO = Decimal(0)


@dataclass
class RealizedRow:
    account: str
    instrument: str
    isin: str | None
    quantity: Decimal = ZERO
    proceeds_eur: Decimal = ZERO
    cost_eur: Decimal = ZERO

    @property
    def result_eur(self) -> Decimal:
        return self.proceeds_eur - self.cost_eur


@dataclass
class IncomeRow:
    account: str
    instrument: str
    isin: str | None
    gross_eur: Decimal = ZERO
    withholding_eur: Decimal = ZERO  # tax withheld at source and fees on the payment

    @property
    def net_eur(self) -> Decimal:
        return self.gross_eur - self.withholding_eur


@dataclass
class YearReport:
    year: int
    realized: list[RealizedRow]
    income: list[IncomeRow]
    costs_eur: Decimal  # standalone fees and taxes booked in the year

    @property
    def realized_total_eur(self) -> Decimal:
        return sum((r.result_eur for r in self.realized), ZERO)

    @property
    def income_gross_eur(self) -> Decimal:
        return sum((r.gross_eur for r in self.income), ZERO)

    @property
    def withholding_eur(self) -> Decimal:
        return sum((r.withholding_eur for r in self.income), ZERO)


def report_years(db: Session) -> list[int]:
    """Years in which something was sold or income was received, newest first."""
    years: set[int] = set()
    rows = db.execute(
        select(LedgerTransaction.trade_date, LedgerTransaction.type).where(
            LedgerTransaction.deleted_at.is_(None),
            LedgerTransaction.status == "posted",
            LedgerTransaction.type.in_(("sell", "dividend", "interest", "fee", "tax")),
        )
    )
    for day, _ in rows:
        years.add(day.year)
    return sorted(years, reverse=True)


def year_report(db: Session, year: int, account_id: int | None = None) -> YearReport:
    start, end = date(year, 1, 1), date(year, 12, 31)
    accounts = {a.id: a.name for a in db.scalars(select(Account))}
    names = {i.id: (i.name, i.isin) for i in db.scalars(select(Instrument))}

    realized: dict[tuple[int, int], RealizedRow] = {}
    query = (
        select(LotMatch, LedgerTransaction)
        .join(LedgerTransaction, LedgerTransaction.id == LotMatch.sell_transaction_id)
        .where(
            LedgerTransaction.type == "sell",
            LedgerTransaction.deleted_at.is_(None),
            LedgerTransaction.status == "posted",
            LedgerTransaction.trade_date >= start,
            LedgerTransaction.trade_date <= end,
        )
        .order_by(LedgerTransaction.trade_date, LedgerTransaction.id, LotMatch.id)
    )
    if account_id is not None:
        query = query.where(LotMatch.account_id == account_id)
    for match, _sale in db.execute(query):
        name, isin = names.get(match.instrument_id, (str(match.instrument_id), None))
        row = realized.setdefault(
            (match.account_id, match.instrument_id),
            RealizedRow(accounts.get(match.account_id, "?"), name, isin),
        )
        row.quantity += match.quantity
        row.proceeds_eur += match.proceeds_eur
        row.cost_eur += match.cost_eur

    income: dict[tuple[int, int | None], IncomeRow] = {}
    costs = ZERO
    txs = select(LedgerTransaction).where(
        LedgerTransaction.deleted_at.is_(None),
        LedgerTransaction.status == "posted",
        LedgerTransaction.trade_date >= start,
        LedgerTransaction.trade_date <= end,
        LedgerTransaction.type.in_(("dividend", "interest", "fee", "tax")),
    )
    if account_id is not None:
        txs = txs.where(LedgerTransaction.account_id == account_id)
    for tx in db.scalars(txs.order_by(LedgerTransaction.trade_date, LedgerTransaction.id)):
        domain = to_txin(tx)
        if tx.type in ("fee", "tax"):
            costs += domain.amount_eur or ZERO
            continue
        name, isin = (
            names.get(tx.instrument_id, ("Interest", None))
            if tx.instrument_id is not None
            else ("Interest", None)
        )
        earned = income.setdefault(
            (tx.account_id, tx.instrument_id),
            IncomeRow(accounts.get(tx.account_id, "?"), name, isin),
        )
        earned.gross_eur += domain.amount_eur or ZERO
        earned.withholding_eur += domain.taxes_eur + domain.fees_eur
    return YearReport(
        year=year,
        realized=sorted(realized.values(), key=lambda r: (r.account, r.instrument)),
        income=sorted(income.values(), key=lambda r: (r.account, r.instrument)),
        costs_eur=costs,
    )


def _safe(text: str | None) -> str:
    """Spreadsheets run text that starts with = + - or @ as a formula; make it plain text."""
    value = text or ""
    return "'" + value if value[:1] in ("=", "+", "-", "@") else value


def to_csv(report: YearReport) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(
        [
            "section", "year", "account", "instrument", "isin", "quantity", "proceeds_eur",
            "cost_eur", "realized_result_eur", "income_gross_eur", "withholding_eur",
            "income_net_eur",
        ]
    )  # fmt: skip
    for r in report.realized:
        writer.writerow(
            [
                "realized", report.year, _safe(r.account), _safe(r.instrument), r.isin or "",
                r.quantity, r.proceeds_eur, r.cost_eur, r.result_eur, "", "", "",
            ]
        )  # fmt: skip
    for i in report.income:
        writer.writerow(
            [
                "income", report.year, _safe(i.account), _safe(i.instrument), i.isin or "",
                "", "", "", "", i.gross_eur, i.withholding_eur, i.net_eur,
            ]
        )  # fmt: skip
    writer.writerow(
        ["costs", report.year, "", "Fees and taxes", "", "", "", "", "-" + str(report.costs_eur)]
        + ["", "", ""]
    )
    writer.writerow(
        [
            "total", report.year, "", "", "", "", "", "", report.realized_total_eur,
            report.income_gross_eur, report.withholding_eur,
            report.income_gross_eur - report.withholding_eur,
        ]
    )  # fmt: skip
    return out.getvalue()


# --- reconciliation -----------------------------------------------------------------------------


@dataclass(frozen=True)
class ReconcileLine:
    instrument_id: int | None
    name: str
    isin: str | None
    ours: Decimal
    broker: Decimal
    difference: Decimal  # broker minus ours
    status: str  # match | difference | missing_at_broker | unknown


def reconcile(
    db: Session,
    account: Account,
    on: date,
    broker_rows: list[tuple[int | None, str | None, Decimal]],
) -> list[ReconcileLine]:
    """Compare the quantities the broker reports on `on` with what the ledger says.

    `broker_rows` are (instrument id, ISIN, quantity); a row may identify the instrument by
    either. Instruments the ledger holds but the broker does not list are reported too. Lines
    with a difference come first, the largest first.
    """
    state = compute_state(db, account, as_of=on)
    ours = {i: p.quantity for i, p in state.positions.items() if p.quantity != 0}
    by_isin = {
        i.isin: i for i in db.scalars(select(Instrument).where(Instrument.deleted_at.is_(None)))
        if i.isin
    }  # fmt: skip
    lines: list[ReconcileLine] = []
    seen: set[int] = set()
    for instrument_id, isin, quantity in broker_rows:
        instrument = db.get(Instrument, instrument_id) if instrument_id is not None else None
        if instrument is None and isin:
            instrument = by_isin.get(isin.strip().upper())
        if instrument is None or instrument.deleted_at is not None:
            lines.append(
                ReconcileLine(None, isin or "?", isin, ZERO, quantity, quantity, "unknown")
            )
            continue
        seen.add(instrument.id)
        mine = ours.get(instrument.id, ZERO)
        diff = quantity - mine
        lines.append(
            ReconcileLine(
                instrument.id, instrument.name, instrument.isin, mine, quantity, diff,
                "match" if diff == 0 else "difference",
            )
        )  # fmt: skip
    for instrument_id, mine in ours.items():
        if instrument_id in seen:
            continue
        instrument = db.get(Instrument, instrument_id)
        lines.append(
            ReconcileLine(
                instrument_id,
                instrument.name if instrument else str(instrument_id),
                instrument.isin if instrument else None,
                mine, ZERO, -mine, "missing_at_broker",
            )
        )  # fmt: skip
    order = {"difference": 0, "missing_at_broker": 0, "unknown": 1, "match": 2}
    return sorted(lines, key=lambda line: (order[line.status], -abs(line.difference), line.name))
