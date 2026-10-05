"""Time-weighted return and XIRR (FR-PF-03). Pure functions on prepared daily series.

Conventions (ADR 0014):

* A series has one point per calendar day: the end-of-day value, the external cash flow of
  that day (money put in is positive) and the income received that day. Income is part of the
  return, not a flow, because with cash tracking off it leaves the portfolio.
* TWR links daily returns ``(V_t + I_t) / (V_{t-1} + F_t) - 1``: the day's flow is treated as
  made at the start of the day. A day whose starting capital is not positive has no return and
  is skipped, and so is the day on which everything was sold (no end value to measure).
* XIRR is the annualised money-weighted rate on ACT/365 dates. The start value is an outflow on
  the baseline day, flows are outflows (contributions) or inflows (withdrawals) on their days,
  income is an inflow, and the end value is an inflow on the last day.

Everything is Decimal. ``exp`` and ``ln`` are Decimal's own, at 40 digits.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext

ZERO = Decimal(0)
ONE = Decimal(1)
_PRECISION = 40
_TOLERANCE = Decimal("1E-18")


@dataclass(frozen=True)
class DailyPoint:
    day: date
    value: Decimal  # end of day
    flow: Decimal = ZERO  # external money in (+) or out (-), made at the start of the day
    income: Decimal = ZERO  # dividends and interest received this day


def twr_index(points: Sequence[DailyPoint]) -> list[tuple[date, Decimal]]:
    """The chained index, 1 at the first point (the baseline: its flow is ignored)."""
    if not points:
        return []
    index = ONE
    out = [(points[0].day, index)]
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        for previous, point in zip(points, points[1:], strict=False):
            capital = previous.value + point.flow
            ended = point.value + point.income
            sold_out = point.value == 0 and point.flow < 0
            if capital > 0 and not sold_out:
                index = index * (ended / capital)
            out.append((point.day, index))
    return out


def twr(points: Sequence[DailyPoint]) -> Decimal | None:
    """Total time-weighted return over the series (0.05 = 5%); None for fewer than two days."""
    if len(points) < 2:
        return None
    return twr_index(points)[-1][1] - ONE


def annualise(rate: Decimal, days: int) -> Decimal | None:
    """Scale a return over `days` calendar days to a year (compounding, 365-day year)."""
    if days <= 0 or rate <= -ONE:
        return None
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        return ((ONE + rate).ln() * Decimal(365) / Decimal(days)).exp() - ONE


def xirr_flows(points: Sequence[DailyPoint]) -> list[tuple[date, Decimal]]:
    """The investor's cash flows for a series: what goes in is negative, what comes out and the
    final value positive."""
    if len(points) < 2:
        return []
    flows: list[tuple[date, Decimal]] = []
    if points[0].value > 0:
        flows.append((points[0].day, -points[0].value))
    for point in points[1:]:
        net = point.income - point.flow
        if net != 0:
            flows.append((point.day, net))
    last = points[-1]
    if last.value != 0:
        flows.append((last.day, last.value))
    return flows


def xirr(flows: Sequence[tuple[date, Decimal]]) -> Decimal | None:
    """The annual rate r with sum(cf / (1+r)^(days/365)) = 0; None when no such rate exists
    (all flows the same sign, or nothing to compare)."""
    if len(flows) < 2:
        return None
    if not (any(cf > 0 for _, cf in flows) and any(cf < 0 for _, cf in flows)):
        return None
    ordered = sorted(flows, key=lambda f: f[0])
    start = ordered[0][0]
    years = [Decimal((d - start).days) / Decimal(365) for d, _ in ordered]
    amounts = [cf for _, cf in ordered]

    with localcontext() as ctx:
        ctx.prec = _PRECISION

        # work in x = ln(1 + r), so the sum is a plain sum of exponentials
        def g(x: Decimal) -> Decimal:
            return sum((cf * (-t * x).exp() for cf, t in zip(amounts, years, strict=True)), ZERO)

        def dg(x: Decimal) -> Decimal:
            return sum(
                (-t * cf * (-t * x).exp() for cf, t in zip(amounts, years, strict=True)), ZERO
            )

        lo, hi = Decimal("1E-6").ln(), Decimal(1001).ln()  # -99.9999% to +100,000% a year
        g_lo, g_hi = g(lo), g(hi)
        if g_lo == 0:
            return lo.exp() - ONE
        if g_hi == 0:
            return hi.exp() - ONE
        if (g_lo > 0) == (g_hi > 0):
            return None
        x = Decimal("1.1").ln()  # start from a 10% rate
        for _ in range(200):
            value = g(x)
            if value == 0:
                break
            if (value > 0) == (g_lo > 0):
                lo = x
            else:
                hi = x
            slope = dg(x)
            step = x - value / slope if slope != 0 else lo - ONE
            if not (lo < step < hi):
                step = (lo + hi) / 2  # Newton left the bracket: bisect instead
            if abs(step - x) < _TOLERANCE:
                x = step
                break
            x = step
        return x.exp() - ONE


@dataclass(frozen=True)
class ReturnFigures:
    twr: Decimal | None
    twr_annualised: Decimal | None
    xirr: Decimal | None
    start: date
    end: date


def return_figures(points: Sequence[DailyPoint]) -> ReturnFigures | None:
    """TWR, annualised TWR and XIRR over a series; None for fewer than two days."""
    if len(points) < 2:
        return None
    rate = twr(points)
    days = (points[-1].day - points[0].day).days
    return ReturnFigures(
        twr=rate,
        twr_annualised=None if rate is None else annualise(rate, days),
        xirr=xirr(xirr_flows(points)),
        start=points[0].day,
        end=points[-1].day,
    )
