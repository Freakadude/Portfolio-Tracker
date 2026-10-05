"""The quarterly strategy review (FR-ST-08): a summary of one quarter of the active strategy.

It is made by code, without a model: each sleeve's drift from its target at the month ends and on
its worst day, the signals that fired by rule, and what became of the agent's recommendations
(your decisions and, where measured, their outcomes). `build_review` is pure; `gather` reads the
database; `post` puts one item in the inbox per quarter.
"""

from __future__ import annotations

import calendar
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio import analytics_service as svc
from folio.agent import outcomes
from folio.analytics.allocation import drift
from folio.db.models_insight import Recommendation
from folio.db.models_strategy import Notification, Signal, Strategy, StrategyVersion
from folio.notify.service import notify
from folio.strategies.inputs import sleeve_of_instruments
from folio.strategies.schema import SEVERITIES, StrategyDef
from folio.strategies.service import active_definition, managing_strategy

HUNDRED = Decimal(100)
ZERO = Decimal(0)
SOURCE = "digest"


@dataclass(frozen=True)
class Quarter:
    year: int
    number: int  # 1 to 4

    @property
    def label(self) -> str:
        return f"{self.year}Q{self.number}"

    @property
    def start(self) -> date:
        return date(self.year, 3 * (self.number - 1) + 1, 1)

    @property
    def end(self) -> date:
        month = 3 * self.number
        return date(self.year, month, calendar.monthrange(self.year, month)[1])

    @classmethod
    def parse(cls, text: str) -> Quarter:
        year, _, number = text.upper().partition("Q")
        if not (year.isdigit() and number in ("1", "2", "3", "4")):
            raise ValueError("Use a quarter like 2026Q3.")
        return cls(int(year), int(number))

    @classmethod
    def of(cls, day: date) -> Quarter:
        return cls(day.year, (day.month - 1) // 3 + 1)

    def previous(self) -> Quarter:
        return (
            Quarter(self.year - 1, 4) if self.number == 1 else Quarter(self.year, self.number - 1)
        )


@dataclass(frozen=True)
class SleeveIn:
    id: str
    target_pct: Decimal | None
    soft_band_pp: Decimal | None
    hard_band_pp: Decimal | None


@dataclass(frozen=True)
class SignalIn:
    rule_id: str
    severity: str
    day: date


@dataclass(frozen=True)
class DriftPoint:
    day: date
    weight: Decimal  # fraction of the portfolio
    drift_pp: Decimal  # percentage points against the target; positive is overweight


@dataclass(frozen=True)
class SleeveReview:
    id: str
    target_pct: Decimal | None
    month_ends: list[DriftPoint]
    worst: DriftPoint | None  # the day furthest from the target, when there is a target
    days_outside_hard: int
    days_outside_soft: int


@dataclass(frozen=True)
class SignalCount:
    rule_id: str
    count: int
    worst_severity: str


@dataclass(frozen=True)
class RecommendationSummary:
    made: int
    by_status: dict[str, int]
    by_action: dict[str, int]
    track: outcomes.TrackRecord


@dataclass(frozen=True)
class Review:
    quarter: Quarter
    strategy: str
    sleeves: list[SleeveReview]
    signals: list[SignalCount]
    recommendations: RecommendationSummary
    days_with_data: int
    notes: list[str] = field(default_factory=list)


def _month_ends(quarter: Quarter, days: Sequence[date]) -> list[date]:
    """The last day with data in each month of the quarter."""
    out = []
    for offset in range(3):
        month = 3 * (quarter.number - 1) + 1 + offset
        in_month = [d for d in days if d.year == quarter.year and d.month == month]
        if in_month:
            out.append(max(in_month))
    return out


def build_review(
    quarter: Quarter,
    strategy_name: str,
    sleeves: Sequence[SleeveIn],
    weights: Mapping[date, Mapping[str, Decimal]],
    signals: Sequence[SignalIn],
    recs: Sequence[outcomes.Row],
) -> Review:
    days = sorted(d for d in weights if quarter.start <= d <= quarter.end)
    ends = _month_ends(quarter, days)
    notes: list[str] = []
    sleeve_reviews = []
    for sleeve in sleeves:
        target = None if sleeve.target_pct is None else sleeve.target_pct / HUNDRED
        points: dict[date, DriftPoint] = {}
        for d in days:
            weight = weights[d].get(sleeve.id, ZERO)
            result = drift(weight, target)
            points[d] = DriftPoint(d, weight, ZERO if result is None else result.pp * HUNDRED)
        worst = None
        outside_hard = outside_soft = 0
        if target is not None and points:
            worst = max(points.values(), key=lambda p: (abs(p.drift_pp), p.day))
            for p in points.values():
                gap = abs(p.drift_pp)
                if sleeve.hard_band_pp is not None and gap > sleeve.hard_band_pp:
                    outside_hard += 1
                elif sleeve.soft_band_pp is not None and gap > sleeve.soft_band_pp:
                    outside_soft += 1
        elif target is None:
            notes.append(f"{sleeve.id} has no target yet, so its drift cannot be judged.")
        sleeve_reviews.append(
            SleeveReview(
                id=sleeve.id,
                target_pct=sleeve.target_pct,
                month_ends=[points[d] for d in ends],
                worst=worst,
                days_outside_hard=outside_hard,
                days_outside_soft=outside_soft,
            )
        )
    by_rule: dict[str, list[str]] = {}
    for s in signals:
        by_rule.setdefault(s.rule_id, []).append(s.severity)
    signal_counts = [
        SignalCount(
            rule_id=rule,
            count=len(found),
            worst_severity=max(found, key=lambda v: SEVERITIES.index(v)),
        )
        for rule, found in sorted(by_rule.items())
    ]
    summary = RecommendationSummary(
        made=len(recs),
        by_status=dict(Counter(r.status for r in recs)),
        by_action=dict(Counter(r.action_type for r in recs)),
        track=outcomes.summarise(recs),
    )
    if not days:
        notes.append("There is no portfolio history in this quarter.")
    return Review(quarter, strategy_name, sleeve_reviews, signal_counts, summary, len(days), notes)


def _pp(value: Decimal) -> str:
    return f"{value:+.1f} pp"


def render(review: Review) -> str:
    """The summary as plain text, for the inbox and the page."""
    q = review.quarter
    lines = [f"Quarterly review of {review.strategy}, {q.label} ({q.start} to {q.end})."]
    for sleeve in review.sleeves:
        if sleeve.target_pct is None:
            lines.append(f"- {sleeve.id}: no target set.")
            continue
        ends = ", ".join(f"{p.day:%b} {_pp(p.drift_pp)}" for p in sleeve.month_ends) or "no data"
        worst = (
            ""
            if sleeve.worst is None
            else f"; furthest {_pp(sleeve.worst.drift_pp)} on {sleeve.worst.day}"
        )
        outside = (
            f"; {sleeve.days_outside_hard} day(s) outside the hard band, "
            f"{sleeve.days_outside_soft} outside the soft band"
            if sleeve.days_outside_hard or sleeve.days_outside_soft
            else ""
        )
        lines.append(
            f"- {sleeve.id} (target {sleeve.target_pct}%): month ends {ends}{worst}{outside}."
        )
    if review.signals:
        fired = "; ".join(
            f"{s.rule_id} {s.count}x (worst {s.worst_severity})" for s in review.signals
        )
        lines.append(f"Signals that fired: {fired}.")
    else:
        lines.append("No signals fired.")
    rec = review.recommendations
    if rec.made:
        status = ", ".join(f"{n} {k}" for k, n in sorted(rec.by_status.items()))
        lines.append(f"The agent made {rec.made} recommendation(s): {status}.")
        for action in rec.track.actions:
            h = next((x for x in action.by_horizon if x.days == rec.track.decision_horizon), None)
            if action.scored_type and h is not None and h.scored:
                lines.append(
                    f"- {action.action_type}: {h.hits} of {h.scored} would have been right after "
                    f"{h.days} days (price only)."
                )
    else:
        lines.append("The agent made no recommendations.")
    lines.extend(review.notes)
    return "\n".join(lines)


# --- the database side --------------------------------------------------------------------------


def _definition(db: Session) -> tuple[Strategy, StrategyDef] | None:
    strategy = managing_strategy(db)
    if strategy is None:
        return None
    return strategy, active_definition(db, strategy)


def gather(db: Session, quarter: Quarter, today: date) -> Review | None:
    """The review of `quarter` for the active strategy, or None when there is none."""
    found = _definition(db)
    if found is None:
        return None
    strategy, definition = found
    mapping = sleeve_of_instruments(db, definition)
    weights: dict[date, dict[str, Decimal]] = {}
    ctx = svc.get_context(db, min(today, quarter.end))
    if not ctx.empty:
        for day, point in zip(ctx.days, ctx.points, strict=True):
            if not quarter.start <= day <= quarter.end:
                continue
            totals: dict[str, Decimal] = {}
            total = ZERO
            for h in point.holdings:
                if h.value_eur is None:
                    continue
                total += h.value_eur
                name = mapping.get(h.instrument_id)
                if name is not None:
                    totals[name] = totals.get(name, ZERO) + h.value_eur
            if total > 0:
                weights[day] = {k: v / total for k, v in totals.items()}
    version_ids = list(
        db.scalars(select(StrategyVersion.id).where(StrategyVersion.strategy_id == strategy.id))
    )
    start = datetime.combine(quarter.start, time.min, tzinfo=UTC)
    end = datetime.combine(quarter.end, time.max, tzinfo=UTC)
    signals = [
        SignalIn(s.rule_id, s.severity, s.ts.date())
        for s in db.scalars(
            select(Signal).where(
                Signal.strategy_version_id.in_(version_ids),
                Signal.shadow.is_(False),
                Signal.ts >= start,
                Signal.ts <= end,
            )
        )
    ]
    recs = [
        outcomes.Row(r.action_type, r.status, r.outcome or {})
        for r in db.scalars(
            select(Recommendation).where(
                Recommendation.status != "refused",
                Recommendation.created_at >= start,
                Recommendation.created_at <= end,
            )
        )
    ]
    sleeves = [
        SleeveIn(s.id, s.target_pct, s.soft_band_pp, s.hard_band_pp) for s in definition.sleeves
    ]
    return build_review(quarter, strategy.name, sleeves, weights, signals, recs)


def post(db: Session, review: Review, now: datetime) -> Notification | None:
    """One inbox item for the quarter. A second call for the same quarter makes none."""
    subject = f"review:{review.quarter.label}"
    exists = db.scalar(
        select(Notification.id).where(
            Notification.source == SOURCE, Notification.subject == subject
        )
    )
    if exists is not None:
        return None
    return notify(
        db,
        source=SOURCE,
        severity="info",
        subject=subject,
        title=f"Quarterly review {review.quarter.label}: {review.strategy}",
        body=render(review),
        push_title="Folio quarterly review",
        push_body=f"Your quarterly review for {review.quarter.label} is ready.",
        push_body_anonymous="Folio has a new review.",
        link=f"/strategies/review?quarter={review.quarter.label}",
        now=now,
    )
