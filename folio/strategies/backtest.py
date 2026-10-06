"""Backtest a rule over history (FR-ST-06): when would it have fired?

The strategy's rules are evaluated for every past trading day on what the portfolio looked like
that day (sleeve weights, closes, the time-weighted index, macro series), and the signals are
let through the same dedup as live ones (cooldown and worsening, in memory), so the list is what
the inbox would have shown. Nothing is stored and nothing is sent.

It judges the rule as written today against the history as it is stored today: the sleeves keep
the members and targets of the strategy being tested, and the days are the ones the portfolio
existed. Rules that depend on something that was not kept for past days are named as not
backtestable, with the reason, instead of being guessed.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio import analytics_service as svc
from folio.analytics.returns import twr_index
from folio.analytics.risk import daily_returns
from folio.db.models_analytics import MacroPoint, MacroSeries
from folio.db.models_ledger import Instrument, Listing, PriceBar
from folio.strategies.inputs import HISTORY_DAYS, sleeve_of_instruments
from folio.strategies.rules import PositionState, RuleInputs, SleeveState, evaluate
from folio.strategies.schema import Severity, StrategyDef
from folio.strategies.signals import Open, should_fire

ZERO = Decimal(0)
MAX_DAYS = 1100  # about three years of daily evaluation
NOT_BACKTESTABLE = {
    "stale_data": "It looks at how fresh today's prices are, which is not kept for past days.",
    "contribution_due": "It depends on the contribution plan's dates as they stand now.",
    "thesis_review_due": "It depends on the thesis review dates as they stand now.",
    "concentration_limit": (
        "It needs the ETF holdings of each past day; only the snapshots you saved are known."
    ),
}


class BacktestError(ValueError):
    """The request cannot be run; the message is for the owner."""


@dataclass(frozen=True)
class Meta:
    name: str
    isin: str | None
    currency: str | None


@dataclass
class History:
    """What the portfolio looked like on each past day, prepared once."""

    days: list[date]
    values: list[dict[int, Decimal]]  # per day: instrument -> value in euro (valued holdings)
    eur_closes: dict[int, list[Decimal | None]]  # aligned with `days`
    native_dates: dict[int, list[date]]  # a close in the trading currency, for price levels
    native_closes: dict[int, list[Decimal]]
    meta: dict[int, Meta]
    sleeve_of: dict[int, str]
    index: list[tuple[date, Decimal]]
    sleeve_returns: dict[str, list[tuple[date, Decimal]]]
    macro: dict[str, list[tuple[date, Decimal]]]
    trading_days: frozenset[date]
    cash: list[Decimal | None]  # per day, when an account tracks cash


@dataclass(frozen=True)
class Firing:
    day: date
    rule_id: str
    rule_type: str
    subject: str
    severity: Severity
    value: Decimal | None
    message: str


@dataclass(frozen=True)
class RuleReport:
    rule_id: str
    rule_type: str
    backtestable: bool
    reason: str | None  # why it could not be tested, or what it was waiting for
    days_true: int  # days the condition held, before the dedup
    fired: int


@dataclass
class Backtest:
    start: date
    end: date
    days_checked: int
    firings: list[Firing]
    rules: list[RuleReport]
    notes: list[str] = field(default_factory=list)


# --- one day's inputs ---------------------------------------------------------------------------


def _window(
    series: list[tuple[date, Decimal]], first: date, last: date
) -> list[tuple[date, Decimal]]:
    dates = [d for d, _ in series]
    return series[bisect_left(dates, first) : bisect_right(dates, last)]


def inputs_on(h: History, strategy: StrategyDef, i: int, since: date) -> RuleInputs:
    day = h.days[i]
    first = day - timedelta(days=HISTORY_DAYS)
    lo = bisect_left(h.days, first)
    held = h.values[i]
    total = sum(held.values(), ZERO)
    by_sleeve: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for instrument_id, value in held.items():
        name = h.sleeve_of.get(instrument_id)
        if name is not None:
            by_sleeve[name] += value
    sleeves = {
        spec.id: SleeveState(ZERO if total == 0 else by_sleeve[spec.id] / total, by_sleeve[spec.id])
        for spec in strategy.sleeves
    }
    positions: list[PositionState] = []
    for instrument_id, value in held.items():
        meta = h.meta.get(instrument_id, Meta(str(instrument_id), None, None))
        series = h.eur_closes.get(instrument_id)
        closes = (
            []
            if series is None
            else [(h.days[k], c) for k in range(lo, i + 1) if (c := series[k]) is not None]
        )
        dates = h.native_dates.get(instrument_id, [])
        at = bisect_right(dates, day) - 1
        positions.append(
            PositionState(
                instrument_id=instrument_id,
                name=meta.name,
                isin=meta.isin,
                sleeve=h.sleeve_of.get(instrument_id),
                weight=None if total == 0 else value / total,
                closes_eur=closes,
                close=h.native_closes[instrument_id][at] if at >= 0 else None,
                currency=meta.currency,
            )
        )
    return RuleInputs(
        today=day,
        total_eur=total,
        sleeves=sleeves,
        positions=positions,
        portfolio_index=_window(h.index, first, day),
        sleeve_returns={k: _window(v, first, day) for k, v in h.sleeve_returns.items()},
        macro={k: _window(v, first, day) for k, v in h.macro.items()},
        stale=[],
        tracked_cash_eur=h.cash[i],
        strategy_since=since,
    )


# --- the replay ---------------------------------------------------------------------------------


def run_backtest(
    strategy: StrategyDef,
    h: History,
    start: date,
    end: date,
    rule_ids: list[str] | None = None,
) -> Backtest:
    """Evaluate the chosen rules (all, when none are named) on every trading day from `start` to
    `end` and let the findings through the live dedup."""
    known = {r.id for r in strategy.rules}
    wanted = set(rule_ids) if rule_ids else known
    unknown = wanted - known
    if unknown:
        raise BacktestError(f"The strategy has no rule {', '.join(sorted(unknown))}.")
    testable = [r for r in strategy.rules if r.id in wanted and r.type not in NOT_BACKTESTABLE]
    trimmed = strategy.model_copy(update={"rules": testable})
    rules = {r.id: r for r in testable}
    reasons: dict[str, str | None] = {}
    days_true: dict[str, int] = defaultdict(int)
    fired_count: dict[str, int] = defaultdict(int)
    firings: list[Firing] = []
    state: dict[str, Open] = {}
    checked = 0
    for i, day in enumerate(h.days):
        if day < start or day > end or day not in h.trading_days or not h.values[i]:
            continue  # outside the range, a closed day, or nothing held yet
        checked += 1
        evaluation = evaluate(trimmed, inputs_on(h, trimmed, i, start))
        for st in evaluation.statuses:
            reasons[st.rule_id] = st.reason  # the last day's answer: what it is waiting for
        now = datetime.combine(day, time(23, 0), UTC)
        seen: dict[str, Open] = {}
        for f in evaluation.findings:
            days_true[f.rule_id] += 1
            rule = rules[f.rule_id]
            previous = state.get(f.dedup_key)
            if should_fire(previous, f.value, rule.cooldown_days, rule.worsen_step, now):
                fired_count[f.rule_id] += 1
                firings.append(
                    Firing(day, f.rule_id, f.rule_type, f.subject, f.severity, f.value, f.title)
                )
                seen[f.dedup_key] = Open(now, f.value)
            elif previous is not None:
                seen[f.dedup_key] = previous
        state = seen  # a condition that cleared is forgotten, so its next breach fires at once
    reports = [
        RuleReport(
            r.id,
            r.type,
            r.type not in NOT_BACKTESTABLE,
            NOT_BACKTESTABLE.get(r.type) if r.type in NOT_BACKTESTABLE else reasons.get(r.id),
            days_true[r.id],
            fired_count[r.id],
        )
        for r in strategy.rules
        if r.id in wanted
    ]
    notes: list[str] = []
    if checked == 0:
        notes.append("There are no trading days with data in that range.")
    return Backtest(start, end, checked, firings, reports, notes)


# --- the database side --------------------------------------------------------------------------


def load_history(db: Session, strategy: StrategyDef, end: date) -> History | None:
    """The history of the portfolio up to `end`, or None when there is none."""
    ctx = svc.get_context(db, end)
    if ctx.empty:
        return None
    mapping = sleeve_of_instruments(db, strategy)
    instruments = {i.id: i for i in db.scalars(select(Instrument))}
    listings = {
        lst.instrument_id: lst
        for lst in db.scalars(select(Listing).where(Listing.pricing_primary.is_(True)))
    }
    values: list[dict[int, Decimal]] = []
    cash: list[Decimal | None] = []
    for point in ctx.points:
        held: dict[int, Decimal] = {}
        for holding in point.holdings:
            if holding.quantity > 0 and holding.value_eur is not None:
                held[holding.instrument_id] = (
                    held.get(holding.instrument_id, ZERO) + holding.value_eur
                )
        values.append(held)
        cash.append(point.cash_eur if ctx.tracks_cash else None)
    ever = {iid for held in values for iid in held}
    native_dates: dict[int, list[date]] = {}
    native_closes: dict[int, list[Decimal]] = {}
    for iid in ever:
        listing = listings.get(iid)
        if listing is None:
            continue
        bars = db.execute(
            select(PriceBar.date, PriceBar.close)
            .where(PriceBar.listing_id == listing.id, PriceBar.date <= end)
            .order_by(PriceBar.date)
        ).all()
        native_dates[iid] = [d for d, _ in bars]
        native_closes[iid] = [c for _, c in bars]
    meta = {
        iid: Meta(
            instruments[iid].name,
            instruments[iid].isin,
            None if iid not in listings else listings[iid].currency,
        )
        for iid in ever
        if iid in instruments
    }
    start = ctx.days[0]
    index = twr_index(svc.portfolio_series(ctx))
    sleeve_returns: dict[str, list[tuple[date, Decimal]]] = {}
    for spec in strategy.sleeves:
        ids = [i for i, name in mapping.items() if name == spec.id]
        series = svc.instrument_series(ctx, ids, start, end)
        sleeve_returns[spec.id] = daily_returns(twr_index(series), set(ctx.trading_days))
    macro: dict[str, list[tuple[date, Decimal]]] = {}
    for code, wanted in strategy.macro_series.items():
        row = db.scalar(
            select(MacroSeries).where(
                MacroSeries.code == wanted.code, MacroSeries.source == wanted.source
            )
        )
        if row is not None:
            macro[code] = [
                (p.date, p.value)
                for p in db.scalars(
                    select(MacroPoint)
                    .where(MacroPoint.series_id == row.id)
                    .order_by(MacroPoint.date)
                )
            ]
    return History(
        days=list(ctx.days),
        values=values,
        eur_closes={iid: list(ctx.prices.get(iid, [])) for iid in ever if iid in ctx.prices},
        native_dates=native_dates,
        native_closes=native_closes,
        meta=meta,
        sleeve_of=mapping,
        index=index,
        sleeve_returns=sleeve_returns,
        macro=macro,
        trading_days=ctx.trading_days,
        cash=cash,
    )


def backtest(
    db: Session,
    strategy: StrategyDef,
    start: date,
    end: date,
    rule_ids: list[str] | None = None,
) -> Backtest:
    if end < start:
        raise BacktestError("The end of the range is before its start.")
    if (end - start).days > MAX_DAYS:
        raise BacktestError(f"Choose a range of at most {MAX_DAYS} days.")
    history = load_history(db, strategy, end)
    if history is None:
        return Backtest(start, end, 0, [], [], ["The portfolio has no history yet."])
    return run_backtest(strategy, history, start, end, rule_ids)
