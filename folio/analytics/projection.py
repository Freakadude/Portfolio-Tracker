"""Projection of future value by Monte Carlo (FR-PF-12). Pure.

A path starts at the portfolio's value and, each month, adds the contribution and applies a
random growth factor. The assumptions are the owner's: an expected return and a volatility per
year, a monthly contribution, a horizon. The factor is lognormal and scaled so that over a year
its expectation is exactly `1 + return`; with zero volatility it is exact compounding, which the
tests pin. The result is the median and the 10th and 90th percentile of the value after each
month, next to what was simply paid in.

This is the one place in Folio that uses floats, on purpose (ADR 0041): a simulation is
statistical, not accounting. Nothing it computes is stored, and every figure that leaves it is a
`Decimal` rounded to cents. A seed makes a run repeatable, so the same assumptions give the same
chart.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from decimal import Decimal

MAX_YEARS = 40
MAX_PATHS = 5000
CENT = Decimal("0.01")
ZERO = Decimal(0)


class ProjectionError(ValueError):
    """The assumptions cannot be simulated; the message is for the owner."""


@dataclass(frozen=True)
class Assumptions:
    start_value_eur: Decimal
    monthly_contribution_eur: Decimal  # 0 when nothing is planned (owner decision Q4)
    annual_return_pct: Decimal  # expected, e.g. 5
    annual_volatility_pct: Decimal  # e.g. 15
    years: int
    paths: int = 2000
    seed: int = 1


@dataclass(frozen=True)
class Point:
    month: int  # 0 is today
    invested_eur: Decimal  # the start value plus every contribution so far, without any growth
    p10_eur: Decimal
    median_eur: Decimal
    p90_eur: Decimal


@dataclass(frozen=True)
class Projection:
    assumptions: Assumptions
    points: list[Point]


def check(a: Assumptions) -> None:
    if a.start_value_eur < 0:
        raise ProjectionError("The starting value cannot be negative.")
    if a.monthly_contribution_eur < 0:
        raise ProjectionError("The monthly contribution cannot be negative.")
    if not 1 <= a.years <= MAX_YEARS:
        raise ProjectionError(f"Choose a horizon of 1 to {MAX_YEARS} years.")
    if not 1 <= a.paths <= MAX_PATHS:
        raise ProjectionError(f"Use 1 to {MAX_PATHS} simulated paths.")
    if a.annual_return_pct <= Decimal(-100) or a.annual_return_pct > Decimal(100):
        raise ProjectionError("The expected return must be between -100 % and 100 % a year.")
    if not 0 <= a.annual_volatility_pct <= Decimal(100):
        raise ProjectionError("The volatility must be between 0 % and 100 % a year.")


def _money(value: float) -> Decimal:
    return Decimal(f"{value:.2f}")


def _percentile(sorted_values: list[float], q: float) -> float:
    """Linear interpolation between the closest ranks."""
    position = q * (len(sorted_values) - 1)
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return sorted_values[low]
    share = position - low
    return sorted_values[low] * (1 - share) + sorted_values[high] * share


def project(a: Assumptions) -> Projection:
    check(a)
    months = a.years * 12
    mu = float(a.annual_return_pct) / 100.0
    sigma = float(a.annual_volatility_pct) / 100.0
    # monthly log growth: mean so that a year's expected factor is exactly 1 + mu
    log_mean = (math.log1p(mu) - sigma * sigma / 2.0) / 12.0
    log_sd = sigma / math.sqrt(12.0)
    rng = random.Random(a.seed)  # noqa: S311 - a simulation, not a secret
    start = float(a.start_value_eur)
    contribution = float(a.monthly_contribution_eur)
    values = [start] * a.paths
    points = [
        Point(0, a.start_value_eur.quantize(CENT), _money(start), _money(start), _money(start))
    ]
    for month in range(1, months + 1):
        for i in range(a.paths):
            shock = rng.gauss(0.0, 1.0) if log_sd > 0 else 0.0
            values[i] = (values[i] + contribution) * math.exp(log_mean + log_sd * shock)
        ordered = sorted(values)
        points.append(
            Point(
                month,
                (a.start_value_eur + a.monthly_contribution_eur * month).quantize(CENT),
                _money(_percentile(ordered, 0.10)),
                _money(_percentile(ordered, 0.50)),
                _money(_percentile(ordered, 0.90)),
            )
        )
    return Projection(a, points)
