"""Outcome tracking of the agent's recommendations (FR-AG-06). Pure: no database, no clock.

A recommendation stores the last close of each subject when it is made. At +7, +30 and +90 days
the close on that day (or the last one just before it) is compared with it. Only two action types
have an honest direction and are scored: a contribution is a hit when the price is at or above
where it was, a trim when it is at or below. Everything else (hold, watch, review, rebalance,
information) is measured but never counted as a hit or a miss.

The comparison is on price in the trading currency: it judges the call, not the euro result of
what the owner did, and with the few recommendations a personal portfolio produces the hit rates
are small samples. Both are said wherever the numbers are shown.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

HORIZONS = (7, 30, 90)
LOOKBACK_DAYS = 5  # the close used is the last one within this many days before the horizon
GRACE_DAYS = 14  # a horizon this long past with no price is closed as unmeasurable
UP_ACTIONS = frozenset({"direct_contribution"})
DOWN_ACTIONS = frozenset({"trim"})
SCORED_ACTIONS = UP_ACTIONS | DOWN_ACTIONS
DECISIONS = ("accepted", "rejected", "undecided")

ZERO = Decimal(0)
RETURN_PLACES = Decimal("0.000001")


def key(days: int) -> str:
    return f"d{days}"


def horizon_date(created: date, days: int) -> date:
    return created + timedelta(days=days)


def decision_of(status: str) -> str:
    """What the owner did: accepted, rejected, or nothing yet (new, seen, snoozed, expired)."""
    return status if status in ("accepted", "rejected") else "undecided"


def price_return(start: Decimal, end: Decimal) -> Decimal | None:
    """The change as a fraction (0.05 is +5 %); None when the start price is not positive."""
    if start <= 0:
        return None
    return ((end - start) / start).quantize(RETURN_PLACES, rounding=ROUND_HALF_EVEN)


def verdict(action_type: str, mean_return: Decimal | None) -> bool | None:
    """Hit (True), miss (False) or not scored (None)."""
    if mean_return is None or action_type not in SCORED_ACTIONS:
        return None
    if action_type in UP_ACTIONS:
        return mean_return >= 0
    return mean_return <= 0


def pending(created: date, today: date, outcome: Mapping[str, Any]) -> list[int]:
    """Horizons that have passed and are not measured yet."""
    return [d for d in HORIZONS if key(d) not in outcome and horizon_date(created, d) <= today]


def measure(
    action_type: str,
    starts: Mapping[str, Decimal],
    ends: Mapping[str, Decimal | None],
    measured_on: date,
) -> dict[str, Any]:
    """The outcome of one horizon, as stored. `ends` holds the close at the horizon per subject
    (None when there is no price)."""
    subjects: dict[str, dict[str, str]] = {}
    returns: list[Decimal] = []
    for name, start in starts.items():
        end = ends.get(name)
        if end is None:
            continue
        change = price_return(start, end)
        if change is None:
            continue
        subjects[name] = {"start": str(start), "end": str(end), "return": str(change)}
        returns.append(change)
    mean = (
        None
        if not returns
        else (sum(returns, ZERO) / len(returns)).quantize(RETURN_PLACES, rounding=ROUND_HALF_EVEN)
    )
    out: dict[str, Any] = {
        "measured_on": measured_on.isoformat(),
        "subjects": subjects,
        "return": None if mean is None else str(mean),
        "hit": verdict(action_type, mean),
    }
    if not subjects:
        out["note"] = "no price"
    return out


def horizon_due_for_giving_up(created: date, today: date, days: int) -> bool:
    return today > horizon_date(created, days) + timedelta(days=GRACE_DAYS)


# --- the track record ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Row:
    action_type: str
    status: str
    outcome: Mapping[str, Any]


@dataclass(frozen=True)
class HorizonStats:
    days: int
    measured: int  # recommendations with a price comparison at this horizon
    scored: int  # of those, the ones with a hit or a miss
    hits: int
    hit_rate: Decimal | None  # hits / scored
    avg_return: Decimal | None  # mean of the recommendations' mean returns


@dataclass(frozen=True)
class ActionStats:
    action_type: str
    scored_type: bool
    count: int
    by_horizon: list[HorizonStats]


@dataclass(frozen=True)
class DecisionStats:
    decision: str
    count: int
    stats: HorizonStats


@dataclass(frozen=True)
class TrackRecord:
    actions: list[ActionStats]
    decisions: list[DecisionStats]
    decision_horizon: int
    total: int


def _stats(days: int, rows: Sequence[Row]) -> HorizonStats:
    measured = scored = hits = 0
    returns: list[Decimal] = []
    for row in rows:
        entry = row.outcome.get(key(days))
        if not entry or entry.get("return") is None:
            continue
        measured += 1
        returns.append(Decimal(str(entry["return"])))
        if entry.get("hit") is not None:
            scored += 1
            hits += 1 if entry["hit"] else 0
    return HorizonStats(
        days=days,
        measured=measured,
        scored=scored,
        hits=hits,
        hit_rate=None if scored == 0 else (Decimal(hits) / Decimal(scored)).quantize(RETURN_PLACES),
        avg_return=None
        if not returns
        else (sum(returns, ZERO) / len(returns)).quantize(RETURN_PLACES),
    )


def summarise(rows: Sequence[Row], decision_horizon: int = 30) -> TrackRecord:
    """Hit rate and mean return by action type and horizon, and by what the owner decided at one
    horizon. Refused items are not passed in."""
    by_action: dict[str, list[Row]] = {}
    for row in rows:
        by_action.setdefault(row.action_type, []).append(row)
    actions = [
        ActionStats(
            action_type=name,
            scored_type=name in SCORED_ACTIONS,
            count=len(group),
            by_horizon=[_stats(d, group) for d in HORIZONS],
        )
        for name, group in sorted(by_action.items())
    ]
    decisions = []
    for name in DECISIONS:
        group = [r for r in rows if decision_of(r.status) == name]
        decisions.append(DecisionStats(name, len(group), _stats(decision_horizon, group)))
    return TrackRecord(actions, decisions, decision_horizon, len(rows))
