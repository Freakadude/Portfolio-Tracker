"""Portfolio valuation maths: holding values, a portfolio's state on one day, and the figures
for a period. Pure functions on prepared data; no I/O.

Without cash tracking, "net contributions" is the money invested from outside (see ADR 0005)
and a portfolio's total P&L is

    market value - net contributions + income - standalone fees and taxes.

An account that tracks cash (ADR 0015) counts only deposits and withdrawals as contributions,
values its cash with its holdings, and so must not add its income or take its costs again.

Period P&L is the same quantity measured between two days. Time-weighted return and XIRR
are in `returns.py`.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

ZERO = Decimal(0)
PERIODS = ("1D", "1W", "1M", "3M", "YTD", "1Y", "3Y", "5Y", "MAX", "CUSTOM")


@dataclass(frozen=True)
class PricePoint:
    """A close in the trading currency and the EUR multiplier for that close's date."""

    date: date
    price: Decimal
    fx: Decimal


@dataclass(frozen=True)
class HoldingValue:
    account_id: int
    instrument_id: int
    quantity: Decimal
    cost_basis_eur: Decimal
    price: PricePoint | None  # None: no close on or before this day
    value_eur: Decimal | None
    net_invested_eur: Decimal = ZERO  # cumulative money put in less taken out
    income_eur: Decimal = ZERO  # cumulative dividends and interest


@dataclass(frozen=True)
class DayPoint:
    """Everything needed to compare two days."""

    day: date
    value_eur: Decimal  # valued holdings only
    net_contributions_eur: Decimal
    income_eur: Decimal
    costs_eur: Decimal  # standalone fees and taxes
    unvalued: int  # holdings that had no price, so are missing from value_eur
    holdings: tuple[HoldingValue, ...] = ()
    # Accounts that track cash (FR-TX-09) hold their income and costs in cash, which is already
    # part of value_eur, so they must not be added to or taken from the result a second time.
    cash_eur: Decimal = ZERO  # included in value_eur
    income_in_cash_eur: Decimal = ZERO  # part of income_eur already inside value_eur
    costs_in_cash_eur: Decimal = ZERO  # part of costs_eur already inside value_eur

    @property
    def outside_income_eur(self) -> Decimal:
        return self.income_eur - self.income_in_cash_eur

    @property
    def outside_costs_eur(self) -> Decimal:
        return self.costs_eur - self.costs_in_cash_eur

    @property
    def total_pnl_eur(self) -> Decimal:
        return (
            self.value_eur
            - self.net_contributions_eur
            + self.outside_income_eur
            - self.outside_costs_eur
        )


def value_holding(
    account_id: int,
    instrument_id: int,
    quantity: Decimal,
    cost_basis_eur: Decimal,
    price: PricePoint | None,
    net_invested_eur: Decimal = ZERO,
    income_eur: Decimal = ZERO,
) -> HoldingValue:
    value = None if price is None else quantity * price.price * price.fx
    return HoldingValue(
        account_id,
        instrument_id,
        quantity,
        cost_basis_eur,
        price,
        value,
        net_invested_eur,
        income_eur,
    )


def make_day_point(
    day: date,
    holdings: list[HoldingValue],
    net_contributions_eur: Decimal,
    income_eur: Decimal,
    costs_eur: Decimal,
    cash_eur: Decimal = ZERO,
    income_in_cash_eur: Decimal = ZERO,
    costs_in_cash_eur: Decimal = ZERO,
) -> DayPoint:
    valued = [h.value_eur for h in holdings if h.value_eur is not None]
    return DayPoint(
        day=day,
        value_eur=sum(valued, ZERO) + cash_eur,
        net_contributions_eur=net_contributions_eur,
        income_eur=income_eur,
        costs_eur=costs_eur,
        unvalued=sum(1 for h in holdings if h.value_eur is None),
        holdings=tuple(holdings),
        cash_eur=cash_eur,
        income_in_cash_eur=income_in_cash_eur,
        costs_in_cash_eur=costs_in_cash_eur,
    )


# --- periods ------------------------------------------------------------------------------------


def subtract_months(day: date, months: int) -> date:
    """Calendar months back, clamping to the month's last day (31 March - 1 month = 29 February)."""
    index = day.year * 12 + (day.month - 1) - months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def resolve_period(
    key: str,
    today: date,
    first_date: date | None,
    custom_start: date | None = None,
    custom_end: date | None = None,
) -> tuple[date, date]:
    """(start, end) for a period key. The start is the day *before* the period begins, the
    valuation the period's change is measured from; flows after it belong to the period."""
    key = key.upper()
    if key not in PERIODS:
        raise ValueError(f"Unknown period {key!r}. Use one of {', '.join(PERIODS)}.")
    if key == "CUSTOM":
        if custom_start is None or custom_end is None:
            raise ValueError("A custom period needs both a start and an end date.")
        if custom_start > custom_end:
            raise ValueError("The start of a period cannot be after its end.")
        return custom_start, custom_end
    if key == "1D":
        return today - timedelta(days=1), today
    if key == "1W":
        return today - timedelta(days=7), today
    if key == "1M":
        return subtract_months(today, 1), today
    if key == "3M":
        return subtract_months(today, 3), today
    if key == "YTD":
        return date(today.year - 1, 12, 31), today
    if key == "1Y":
        return subtract_months(today, 12), today
    if key == "3Y":
        return subtract_months(today, 36), today
    if key == "5Y":
        return subtract_months(today, 60), today
    return (
        first_date - timedelta(days=1) if first_date else today - timedelta(days=1)
    ), today  # MAX


@dataclass(frozen=True)
class PeriodFigures:
    start: date
    end: date
    value_start_eur: Decimal
    value_end_eur: Decimal
    net_flows_eur: Decimal  # money put in (or taken out) during the period
    income_eur: Decimal
    costs_eur: Decimal
    pnl_eur: Decimal
    pnl_ratio: Decimal | None  # over the capital at work: start value plus net flows


def period_figures(start: DayPoint, end: DayPoint) -> PeriodFigures:
    flows = end.net_contributions_eur - start.net_contributions_eur
    income = end.income_eur - start.income_eur
    costs = end.costs_eur - start.costs_eur
    outside_income = end.outside_income_eur - start.outside_income_eur
    outside_costs = end.outside_costs_eur - start.outside_costs_eur
    pnl = (end.value_eur - start.value_eur) - flows + outside_income - outside_costs
    capital = start.value_eur + flows
    return PeriodFigures(
        start=start.day,
        end=end.day,
        value_start_eur=start.value_eur,
        value_end_eur=end.value_eur,
        net_flows_eur=flows,
        income_eur=income,
        costs_eur=costs,
        pnl_eur=pnl,
        pnl_ratio=None if capital <= 0 else pnl / capital,
    )


def pnl_ratio_since_start(end: DayPoint) -> Decimal | None:
    """Total P&L over the money put in; None while nothing has been invested."""
    contributions = end.net_contributions_eur
    return None if contributions <= 0 else end.total_pnl_eur / contributions
