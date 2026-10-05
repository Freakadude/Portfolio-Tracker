"""Allocation and drift (FR-PF-04).

`drift` is the one place drift is defined. The API and, in Phase 3, the rules engine both call
it, so the number on a chart is the number a rule acts on. Weights, targets and drifts are
fractions of the portfolio (0.25 = 25%), so a drift of 0.03 is three percentage points.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext

ZERO = Decimal(0)

GROUPINGS = ("instrument", "asset_class", "sleeve", "region", "sector", "currency")
UNCLASSIFIED = "Unclassified"


@dataclass(frozen=True)
class Drift:
    actual: Decimal
    target: Decimal
    pp: Decimal  # actual - target; positive means overweight
    relative: Decimal | None  # pp as a share of the target; None when the target is zero
    outside_band: bool | None  # None when no band is set


def drift(actual: Decimal, target: Decimal | None, band: Decimal | None = None) -> Drift | None:
    """How far a weight is from its target, or None when there is no target."""
    if target is None:
        return None
    pp = actual - target
    return Drift(
        actual=actual,
        target=target,
        pp=pp,
        relative=None if target == 0 else pp / target,
        outside_band=None if band is None else abs(pp) > band,
    )


@dataclass(frozen=True)
class Slice:
    key: str  # what the slice is called and what a drill-down filters on
    value_eur: Decimal
    weight: Decimal
    drift: Drift | None


@dataclass(frozen=True)
class Allocation:
    total_eur: Decimal
    slices: list[Slice]


def allocate(
    holdings: Sequence[tuple[str, Decimal]],
    targets: Mapping[str, tuple[Decimal, Decimal | None]] | None = None,
) -> Allocation:
    """Sum values by group and weigh them against the total.

    `holdings` are (group, euro value) pairs. `targets` maps a group to (target weight, band);
    a group that has a target but no holdings still appears, at weight 0, because being
    absent is the biggest underweight there is.
    """
    sums: dict[str, Decimal] = {}
    for key, value in holdings:
        sums[key] = sums.get(key, ZERO) + value
    for key in targets or {}:
        sums.setdefault(key, ZERO)
    with localcontext() as ctx:
        ctx.prec = 40
        total = sum(sums.values(), ZERO)
        slices = []
        for key, value in sums.items():
            weight = ZERO if total == 0 else value / total
            target, band = (targets or {}).get(key, (None, None))
            slices.append(Slice(key, value, weight, drift(weight, target, band)))
    slices.sort(key=lambda s: (-s.value_eur, s.key))
    return Allocation(total, slices)
