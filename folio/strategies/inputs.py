"""The numbers the rules look at, gathered once per run from the analytics context (Phase 2).

A strategy's sleeves are mapped to instruments by the members it lists (ISINs or tags) and,
for a sleeve without members, by the sleeve set on the instrument. So a shadow strategy with
other sleeves is measured on its own terms, not on the active strategy's.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio import analytics_service as svc
from folio.analytics.returns import twr_index
from folio.analytics.risk import daily_returns
from folio.db.models_analytics import MacroPoint, MacroSeries, Sleeve
from folio.db.models_ledger import Instrument
from folio.positions import load_positions
from folio.strategies.rules import PositionState, RuleInputs, SleeveState
from folio.strategies.schema import StrategyDef, is_isin

ZERO = Decimal(0)
HISTORY_DAYS = 400  # a year of closes for drawdowns, plus a margin for moves and correlations


def sleeve_of_instruments(db: Session, strategy: StrategyDef) -> dict[int, str]:
    """Instrument id -> the strategy sleeve it belongs to."""
    instruments = list(db.scalars(select(Instrument).where(Instrument.deleted_at.is_(None))))
    table_names = {s.id: s.name for s in db.scalars(select(Sleeve))}
    spec_ids = {s.id for s in strategy.sleeves}
    out: dict[int, str] = {}
    for spec in strategy.sleeves:
        for member in spec.members:
            for i in instruments:
                if (i.isin == member) if is_isin(member) else member in (i.tags or []):
                    out.setdefault(i.id, spec.id)
    for i in instruments:
        if i.id not in out and i.sleeve_id is not None:
            name = table_names.get(i.sleeve_id)
            if name in spec_ids:
                out[i.id] = name
    return out


def build(db: Session, strategy: StrategyDef, today: date, since: date) -> RuleInputs:
    ctx = svc.get_context(db, today)
    mapping = sleeve_of_instruments(db, strategy)
    start = today - timedelta(days=HISTORY_DAYS)

    sleeve_values: dict[str, Decimal] = defaultdict(lambda: ZERO)
    total = ZERO
    if not ctx.empty:
        point = ctx.points[ctx.index(today)]
        for h in point.holdings:
            if h.value_eur is None:
                continue
            total += h.value_eur
            name = mapping.get(h.instrument_id)
            if name is not None:
                sleeve_values[name] += h.value_eur
    sleeves = {
        spec.id: SleeveState(
            ZERO if total == 0 else sleeve_values[spec.id] / total, sleeve_values[spec.id]
        )
        for spec in strategy.sleeves
    }

    rows, _ = load_positions(db, today=today)
    by_instrument: dict[int, list] = defaultdict(list)  # type: ignore[type-arg]
    for r in rows:
        by_instrument[r.instrument.id].append(r)
    positions: list[PositionState] = []
    stale: list[str] = []
    for instrument_id, group in by_instrument.items():
        first = group[0]
        weights = [r.weight for r in group if r.weight is not None]
        closes: list[tuple[date, Decimal]] = []
        if instrument_id in ctx.prices:
            closes = [
                (d, p)
                for d, p in zip(ctx.days, ctx.prices[instrument_id], strict=True)
                if p is not None and d >= start
            ]
        if first.price is not None and first.price.stale:
            stale.append(first.instrument.name)
        positions.append(
            PositionState(
                instrument_id=instrument_id,
                name=first.instrument.name,
                isin=first.instrument.isin,
                sleeve=mapping.get(instrument_id),
                weight=sum(weights, ZERO) if weights else None,
                closes_eur=closes,
                close=None if first.price is None else first.price.close,
                currency=None if first.listing is None else first.listing.currency,
            )
        )

    index: list[tuple[date, Decimal]] = []
    sleeve_returns: dict[str, list[tuple[date, Decimal]]] = {}
    if not ctx.empty:
        index = [(d, v) for d, v in twr_index(svc.portfolio_series(ctx)) if d >= start]
        for spec in strategy.sleeves:
            ids = [i for i, name in mapping.items() if name == spec.id]
            series = svc.instrument_series(ctx, ids, start, today)
            sleeve_returns[spec.id] = daily_returns(twr_index(series), set(ctx.trading_days))

    macro: dict[str, list[tuple[date, Decimal]]] = {}
    for code, wanted in strategy.macro_series.items():
        series_row = db.scalar(
            select(MacroSeries).where(
                MacroSeries.code == wanted.code, MacroSeries.source == wanted.source
            )
        )
        if series_row is None:
            continue
        macro[code] = [
            (p.date, p.value)
            for p in db.scalars(
                select(MacroPoint)
                .where(MacroPoint.series_id == series_row.id, MacroPoint.date >= start)
                .order_by(MacroPoint.date)
            )
        ]

    tracked_cash = None
    if not ctx.empty and ctx.tracks_cash:
        tracked_cash = ctx.points[ctx.index(today)].cash_eur

    return RuleInputs(
        today=today,
        total_eur=total,
        sleeves=sleeves,
        positions=positions,
        portfolio_index=index,
        sleeve_returns=sleeve_returns,
        macro=macro,
        stale=stale,
        tracked_cash_eur=tracked_cash,
        strategy_since=since,
    )
