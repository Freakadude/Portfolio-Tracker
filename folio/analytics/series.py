"""Chart series: rebasing, monthly returns, income by month and the return bridge.

Pure functions on dated values. Used by the comparison, monthly-returns, income and
return-bridge widgets (FR-PF-08, FR-MD-12, FR-DB widget library).
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext

ZERO = Decimal(0)
ONE = Decimal(1)
HUNDRED = Decimal(100)


def rebase(series: Sequence[tuple[date, Decimal]], start: date) -> list[tuple[date, Decimal]]:
    """The series scaled to 100 at `start` (or the last value before it, else its first value);
    points before `start` are dropped. Empty when the base is zero or missing."""
    if not series:
        return []
    days = [d for d, _ in series]
    at = bisect_right(days, start)
    base = series[at - 1][1] if at > 0 else series[0][1]
    if base == 0:
        return []
    with localcontext() as ctx:
        ctx.prec = 40
        return [(d, v / base * HUNDRED) for d, v in series if d >= start]


def monthly_returns(index: Sequence[tuple[date, Decimal]]) -> dict[tuple[int, int], Decimal]:
    """Return of each calendar month from a time-weighted index: month-end over the previous
    month-end (the first month starts at the index's first point)."""
    result: dict[tuple[int, int], Decimal] = {}
    if len(index) < 2:
        return result
    last_of_month: dict[tuple[int, int], Decimal] = {}
    for day, level in index:
        last_of_month[(day.year, day.month)] = level
    previous = index[0][1]
    with localcontext() as ctx:
        ctx.prec = 40
        for key in sorted(last_of_month):
            level = last_of_month[key]
            if previous != 0:
                result[key] = level / previous - ONE
            previous = level
    return result


def by_month(items: Sequence[tuple[date, Decimal]]) -> dict[tuple[int, int], Decimal]:
    """Sum dated amounts (dividends, interest) into calendar months."""
    out: dict[tuple[int, int], Decimal] = {}
    for day, amount in items:
        key = (day.year, day.month)
        out[key] = out.get(key, ZERO) + amount
    return out


@dataclass(frozen=True)
class BridgeStep:
    label: str  # "start", "contributions", "end", or the position's key
    amount_eur: Decimal
    kind: str  # "total" (a bar from zero) or "delta" (floating step)


def bridge(
    value_start: Decimal, positions: Sequence[tuple[str, Decimal, Decimal, Decimal]]
) -> list[BridgeStep]:
    """A waterfall from the start value to the end value: the money put into positions, then
    each position's gain or loss. `positions` are (label, value_start, value_end, flows); the
    start value should equal their start values."""
    steps = [BridgeStep("start", value_start, "total")]
    contributions = sum((f for *_, f in positions), ZERO)
    steps.append(BridgeStep("contributions", contributions, "delta"))
    end = value_start + contributions
    for label, v_start, v_end, flows in positions:
        gain = v_end - v_start - flows
        steps.append(BridgeStep(label, gain, "delta"))
        end += gain
    steps.append(BridgeStep("end", end, "total"))
    return steps
