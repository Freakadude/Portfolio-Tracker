"""The annual tax-support report (FR-PF-11): what a tax return asks about one calendar year.

Value on 1 January and on 31 December, the money put in and taken out as the returns define
external flows (ADR 0014), income and what was withheld, the costs of trading and the standalone
fees and taxes, the realized result from the lot matches, and the change in unrealized result.
It is support for filling in a return, not tax advice, and the figures are in euro at the rates
stored on each transaction.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio import analytics_service as svc
from folio.analytics.valuation import DayPoint
from folio.db.models import Account
from folio.db.models_ledger import Instrument, LedgerTransaction
from folio.exports import plain
from folio.ledger_service import to_txin
from folio.reports import YearReport, _safe, year_report

ZERO = Decimal(0)


@dataclass(frozen=True)
class HoldingOn:
    account: str
    instrument: str
    isin: str | None
    quantity: Decimal
    value_eur: Decimal | None  # None: no price on or before the day
    cost_basis_eur: Decimal


@dataclass
class TaxSupport:
    year: int
    start: date  # 1 January
    end: date  # 31 December, or the last day with data when the year is not over
    partial: bool
    value_start_eur: Decimal = ZERO
    value_end_eur: Decimal = ZERO
    unvalued_start: int = 0  # holdings with no price, so missing from the value
    unvalued_end: int = 0
    money_in_eur: Decimal = ZERO
    money_out_eur: Decimal = ZERO
    income_gross_eur: Decimal = ZERO
    withholding_eur: Decimal = ZERO
    trade_costs_eur: Decimal = ZERO  # fees and taxes paid on purchases and sales
    other_costs_eur: Decimal = ZERO  # standalone fee and tax transactions
    realized_proceeds_eur: Decimal = ZERO
    realized_cost_eur: Decimal = ZERO
    unrealized_start_eur: Decimal = ZERO
    unrealized_end_eur: Decimal = ZERO
    holdings_start: list[HoldingOn] = field(default_factory=list)
    holdings_end: list[HoldingOn] = field(default_factory=list)

    @property
    def net_contributions_eur(self) -> Decimal:
        return self.money_in_eur - self.money_out_eur

    @property
    def income_net_eur(self) -> Decimal:
        return self.income_gross_eur - self.withholding_eur

    @property
    def realized_result_eur(self) -> Decimal:
        return self.realized_proceeds_eur - self.realized_cost_eur

    @property
    def unrealized_change_eur(self) -> Decimal:
        return self.unrealized_end_eur - self.unrealized_start_eur

    @property
    def costs_eur(self) -> Decimal:
        return self.trade_costs_eur + self.other_costs_eur


def _holdings(
    db: Session, point: DayPoint, account_names: dict[int, str]
) -> tuple[list[HoldingOn], Decimal, int]:
    """The positions on a day, the unrealized result of the valued ones and how many have no
    price."""
    names = {i.id: (i.name, i.isin) for i in db.scalars(select(Instrument))}
    rows: list[HoldingOn] = []
    unrealized = ZERO
    unvalued = 0
    for h in point.holdings:
        if h.quantity == 0:
            continue
        name, isin = names.get(h.instrument_id, (str(h.instrument_id), None))
        rows.append(
            HoldingOn(
                account_names.get(h.account_id, "?"), name, isin, h.quantity, h.value_eur,
                h.cost_basis_eur,
            )
        )  # fmt: skip
        if h.value_eur is None:
            unvalued += 1
        else:
            unrealized += h.value_eur - h.cost_basis_eur
    rows.sort(key=lambda r: (r.account, r.instrument))
    return rows, unrealized, unvalued


def tax_support(db: Session, year: int, today: date, account_id: int | None = None) -> TaxSupport:
    start, full_end = date(year, 1, 1), date(year, 12, 31)
    end = min(full_end, today)
    report = TaxSupport(year, start, end, partial=end < full_end)
    accounts = {a.id: a.name for a in db.scalars(select(Account))}
    ctx = svc.get_context(db, end, account_id)
    if not ctx.empty:
        first = ctx.points[ctx.index(start)]
        last = ctx.points[ctx.index(end)]
        report.value_start_eur, report.value_end_eur = first.value_eur, last.value_eur
        report.holdings_start, report.unrealized_start_eur, report.unvalued_start = _holdings(
            db, first, accounts
        )
        report.holdings_end, report.unrealized_end_eur, report.unvalued_end = _holdings(
            db, last, accounts
        )
        for before, point in zip(ctx.points, ctx.points[1:], strict=False):
            if start <= point.day <= end:
                delta = point.net_contributions_eur - before.net_contributions_eur
                if delta > 0:
                    report.money_in_eur += delta
                else:
                    report.money_out_eur -= delta
    flows: YearReport = year_report(db, year, account_id)
    report.income_gross_eur = flows.income_gross_eur
    report.withholding_eur = flows.withholding_eur
    report.other_costs_eur = flows.costs_eur
    report.realized_proceeds_eur = sum((r.proceeds_eur for r in flows.realized), ZERO)
    report.realized_cost_eur = sum((r.cost_eur for r in flows.realized), ZERO)
    trades = select(LedgerTransaction).where(
        LedgerTransaction.deleted_at.is_(None),
        LedgerTransaction.status == "posted",
        LedgerTransaction.type.in_(("buy", "sell")),
        LedgerTransaction.trade_date >= start,
        LedgerTransaction.trade_date <= end,
    )
    if account_id is not None:
        trades = trades.where(LedgerTransaction.account_id == account_id)
    for tx in db.scalars(trades):
        domain = to_txin(tx)
        report.trade_costs_eur += domain.fees_eur + domain.taxes_eur
    return report


def to_csv(report: TaxSupport) -> str:
    """The summary and both lists of positions in one spreadsheet file."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["section", "item", "isin", "quantity", "value_eur", "cost_basis_eur"])
    summary = [
        (f"Value on {report.start}", report.value_start_eur),
        (f"Value on {report.end}", report.value_end_eur),
        ("Money put in (purchases and deposits)", report.money_in_eur),
        ("Money taken out (sales and withdrawals)", report.money_out_eur),
        ("Income received, before tax", report.income_gross_eur),
        ("Tax and fees withheld on income", report.withholding_eur),
        ("Costs of buying and selling", report.trade_costs_eur),
        ("Other fees and taxes", report.other_costs_eur),
        ("Proceeds of sales", report.realized_proceeds_eur),
        ("Cost of what was sold", report.realized_cost_eur),
        ("Realized result", report.realized_result_eur),
        (f"Unrealized result on {report.start}", report.unrealized_start_eur),
        (f"Unrealized result on {report.end}", report.unrealized_end_eur),
        ("Change in unrealized result", report.unrealized_change_eur),
    ]
    for label, value in summary:
        writer.writerow(["summary", label, "", "", plain(value), ""])
    for section, rows in (
        ("holding_start", report.holdings_start),
        ("holding_end", report.holdings_end),
    ):
        for h in rows:
            writer.writerow(
                [
                    section,
                    _safe(f"{h.instrument} ({h.account})"),
                    h.isin or "",
                    plain(h.quantity),
                    plain(h.value_eur),
                    plain(h.cost_basis_eur),
                ]
            )
    return out.getvalue()
