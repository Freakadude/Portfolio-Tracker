"""Risk figures (FR-PF-06): volatility, drawdown, Sharpe, beta and correlation.

All inputs are series of daily returns or a time-weighted index (see `returns.py`), so a
deposit never looks like a gain and a withdrawal never looks like a loss. Weekends and exchange
holidays carry a zero return that would dilute volatility, so callers pass `trading_days` and
only those days are kept; dropping a zero-return day leaves the compounded index unchanged.
"""

from __future__ import annotations

import math
import operator
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext

from folio.analytics.returns import ONE, ZERO, annualise

TRADING_DAYS = 252
_PRECISION = 40
MIN_POINTS = 5  # fewer common days than this and a ratio says nothing


def daily_returns(
    index: Sequence[tuple[date, Decimal]], trading_days: set[date] | None = None
) -> list[tuple[date, Decimal]]:
    """Day-over-day returns of an index, optionally only for days in `trading_days`."""
    out: list[tuple[date, Decimal]] = []
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        for (_, before), (day, after) in zip(index, index[1:], strict=False):
            if before == 0 or (trading_days is not None and day not in trading_days):
                continue
            out.append((day, after / before - ONE))
    return out


def _mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, ZERO) / Decimal(len(values))


def _sample_variance(values: Sequence[Decimal]) -> Decimal:
    mean = _mean(values)
    return sum(((v - mean) ** 2 for v in values), ZERO) / Decimal(len(values) - 1)


def volatility(returns: Sequence[tuple[date, Decimal]]) -> Decimal | None:
    """Annualised standard deviation of daily returns (sample, 252 trading days)."""
    if len(returns) < MIN_POINTS:
        return None
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        values = [r for _, r in returns]
        return _sample_variance(values).sqrt() * Decimal(TRADING_DAYS).sqrt()


@dataclass(frozen=True)
class Drawdown:
    series: list[tuple[date, Decimal]]  # 0 at a new peak, negative under water (-0.1 = -10%)
    maximum: Decimal  # the deepest point of the series (<= 0)
    maximum_start: date | None  # the peak it fell from
    maximum_end: date | None  # the trough
    current: Decimal  # today's distance from the running peak


def drawdown(index: Sequence[tuple[date, Decimal]]) -> Drawdown:
    peak = ZERO
    peak_day: date | None = None
    series: list[tuple[date, Decimal]] = []
    worst = ZERO
    worst_start: date | None = None
    worst_end: date | None = None
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        for day, level in index:
            if level > peak:
                peak, peak_day = level, day
            under = ZERO if peak == 0 else level / peak - ONE
            series.append((day, under))
            if under < worst:
                worst, worst_start, worst_end = under, peak_day, day
    return Drawdown(series, worst, worst_start, worst_end, series[-1][1] if series else ZERO)


def sharpe(
    annual_return: Decimal | None, risk_free: Decimal, annual_volatility: Decimal | None
) -> Decimal | None:
    """(annualised return - risk-free rate) / annualised volatility."""
    if annual_return is None or annual_volatility is None or annual_volatility == 0:
        return None
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        return (annual_return - risk_free) / annual_volatility


def _aligned(
    a: Sequence[tuple[date, Decimal]], b: Sequence[tuple[date, Decimal]]
) -> tuple[list[Decimal], list[Decimal]]:
    other = dict(b)
    xs: list[Decimal] = []
    ys: list[Decimal] = []
    for day, value in a:
        if day in other:
            xs.append(value)
            ys.append(other[day])
    return xs, ys


def beta(
    returns: Sequence[tuple[date, Decimal]], benchmark: Sequence[tuple[date, Decimal]]
) -> Decimal | None:
    """Covariance with the benchmark over the benchmark's variance, on common days."""
    xs, ys = _aligned(returns, benchmark)
    if len(xs) < MIN_POINTS:
        return None
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        variance = _sample_variance(ys)
        if variance == 0:
            return None
        mx, my = _mean(xs), _mean(ys)
        cov = sum(((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)), ZERO) / Decimal(
            len(xs) - 1
        )
        return cov / variance


def correlation(
    a: Sequence[tuple[date, Decimal]], b: Sequence[tuple[date, Decimal]]
) -> Decimal | None:
    xs, ys = _aligned(a, b)
    if len(xs) < MIN_POINTS:
        return None
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        vx, vy = _sample_variance(xs), _sample_variance(ys)
        if vx == 0 or vy == 0:
            return None
        mx, my = _mean(xs), _mean(ys)
        cov = sum(((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)), ZERO) / Decimal(
            len(xs) - 1
        )
        value = cov / (vx.sqrt() * vy.sqrt())
        return max(Decimal(-1), min(ONE, value))  # rounding must never leave [-1, 1]


def _float_correlation(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sxy = syy = 0.0
    for x, y in zip(xs, ys, strict=True):
        dx, dy = x - mx, y - my
        sxx += dx * dx
        sxy += dx * dy
        syy += dy * dy
    if sxx == 0 or syy == 0:
        return None
    return max(-1.0, min(1.0, sxy / math.sqrt(sxx * syy)))


def _standardised(values: Sequence[float]) -> list[float] | None:
    """Deviations from the mean scaled to unit length, so that the correlation of two series
    on the same days is the plain dot product of their standardised forms."""
    mean = sum(values) / len(values)
    deviations = [v - mean for v in values]
    length = math.sqrt(sum(map(operator.mul, deviations, deviations)))
    return None if length == 0 else [d / length for d in deviations]


def _clamped(value: float) -> Decimal:
    return Decimal(repr(max(-1.0, min(1.0, value))))


def correlation_matrix(
    series: Mapping[int, Sequence[tuple[date, Decimal]]],
) -> dict[int, dict[int, Decimal | None]]:
    """Pairwise correlations of daily returns on the days both series have; the diagonal is
    exactly 1.

    A correlation is a unitless statistic shown to two decimals, and a matrix of fifty holdings
    needs over a thousand pairs, which Decimal arithmetic computes about five times slower than
    the dashboard can wait. The pairs are therefore computed in binary floating point
    (accurate to about 1e-15) and returned as Decimal. Money and quantities never pass
    through here (ADR 0014). `correlation` above is the exact Decimal version for one pair.

    Holdings that trade on the same days (the usual case) share one standardised form each,
    and every pair is then a single dot product.
    """
    keys = sorted(series)
    matrix: dict[int, dict[int, Decimal | None]] = {k: {} for k in keys}
    day_sets = {k: tuple(day for day, _ in series[k]) for k in keys}
    if (
        keys
        and len({days for days in day_sets.values()}) == 1
        and len(day_sets[keys[0]]) >= MIN_POINTS
    ):
        forms = {k: _standardised([float(r) for _, r in series[k]]) for k in keys}
        for i, a in enumerate(keys):
            matrix[a][a] = ONE
            for b in keys[i + 1 :]:
                fa, fb = forms[a], forms[b]
                result = (
                    None if fa is None or fb is None else _clamped(sum(map(operator.mul, fa, fb)))
                )
                matrix[a][b] = result
                matrix[b][a] = result
        return matrix
    values = {k: {day: float(r) for day, r in series[k]} for k in keys}
    for i, a in enumerate(keys):
        matrix[a][a] = ONE
        for b in keys[i + 1 :]:
            days = values[a].keys() & values[b].keys()  # order does not matter to a correlation
            result = None
            if len(days) >= MIN_POINTS:
                found = _float_correlation(
                    [values[a][d] for d in days], [values[b][d] for d in days]
                )
                result = None if found is None else Decimal(repr(found))
            matrix[a][b] = result
            matrix[b][a] = result
    return matrix


@dataclass(frozen=True)
class RiskFigures:
    volatility: Decimal | None
    max_drawdown: Decimal
    current_drawdown: Decimal
    sharpe: Decimal | None
    beta: Decimal | None
    annual_return: Decimal | None


def risk_figures(
    index: Sequence[tuple[date, Decimal]],
    trading_days: set[date] | None,
    risk_free: Decimal,
    benchmark_returns: Sequence[tuple[date, Decimal]] | None = None,
) -> RiskFigures:
    """Everything for one index over the window it covers."""
    returns = daily_returns(index, trading_days)
    vol = volatility(returns)
    dd = drawdown(index)
    days = (index[-1][0] - index[0][0]).days if len(index) >= 2 else 0
    total = index[-1][1] / index[0][1] - ONE if len(index) >= 2 and index[0][1] != 0 else None
    yearly = None if total is None else annualise(total, days)
    return RiskFigures(
        volatility=vol,
        max_drawdown=dd.maximum,
        current_drawdown=dd.current,
        sharpe=sharpe(yearly, risk_free, vol),
        beta=None if benchmark_returns is None else beta(returns, benchmark_returns),
        annual_return=yearly,
    )
