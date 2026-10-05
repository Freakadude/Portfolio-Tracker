"""Attribution (FR-PF-07): what each position contributed to the period's return.

A position's contribution in euro is its change in value, minus the money put into it, plus
the income it paid: ``V_end - V_start - flows + income``. The contributions of all positions,
plus an "other" line for costs and income that belong to no position, add up exactly to the
portfolio's period P&L.

Percentage points divide each euro figure by one common denominator, the Modified Dietz
capital (start value plus the flows weighted by the share of the period they were invested,
a flow on the first day counting for the whole period). Because every position shares the
denominator, the points add up exactly to the portfolio's Modified Dietz return (ADR 0014).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext

ZERO = Decimal(0)


@dataclass(frozen=True)
class PositionPeriod:
    key: int | str  # instrument id, or a label for the "other" line
    value_start: Decimal
    value_end: Decimal
    flows: Decimal  # money put in (+) or taken out (-) during the period
    income: Decimal = ZERO


@dataclass(frozen=True)
class Contribution:
    key: int | str
    pnl_eur: Decimal
    points: Decimal | None  # share of the portfolio's return, as a fraction (0.01 = 1 point)


@dataclass(frozen=True)
class Attribution:
    contributions: list[Contribution]
    total_pnl_eur: Decimal
    total_return: Decimal | None  # Modified Dietz
    capital: Decimal  # the denominator


def dietz_capital(
    start: date, end: date, value_start: Decimal, flows: Sequence[tuple[date, Decimal]]
) -> Decimal:
    """Start value plus each flow weighted by the days it was invested (start of its day)."""
    span = (end - start).days
    if span <= 0:
        return value_start
    with localcontext() as ctx:
        ctx.prec = 40
        total = value_start
        for day, flow in flows:
            if start < day <= end:
                total += flow * Decimal((end - day).days + 1) / Decimal(span)
        return total


def attribute(
    items: Sequence[PositionPeriod],
    start: date,
    end: date,
    flow_days: Sequence[tuple[date, Decimal]],
) -> Attribution:
    """Contribution of every item, in euro and in points of the shared return.

    `flow_days` are the portfolio's dated external flows in the period (they set the common
    denominator); the per-item `flows` give each item's own euro result.
    """
    start_value = sum((i.value_start for i in items), ZERO)
    capital = dietz_capital(start, end, start_value, flow_days)
    pnl = {i.key: i.value_end - i.value_start - i.flows + i.income for i in items}
    contributions = [
        Contribution(i.key, pnl[i.key], None if capital <= 0 else pnl[i.key] / capital)
        for i in items
    ]
    total = sum(pnl.values(), ZERO)
    return Attribution(contributions, total, None if capital <= 0 else total / capital, capital)
