"""Portfolio analytics on stored data: returns, history, allocation, risk, attribution,
benchmarks (FR-PF-02 to FR-PF-04, FR-PF-06 to FR-PF-08, FR-MD-12).

`AnalyticsContext` values the portfolio once for every day on which anything happened (a
transaction, a close, a 1 January) and keeps per-instrument series next to it. Everything
else here is arithmetic on that context. Building it costs one pass over the ledger and the
prices, so contexts are cached, keyed on a fingerprint of the stored data (ADR 0016): the first
request after a change pays, the rest are answered from memory (NFR-03).
"""

from __future__ import annotations

import threading
from bisect import bisect_right
from collections import OrderedDict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from folio.analytics.allocation import UNCLASSIFIED, Allocation, allocate
from folio.analytics.attribution import Attribution, PositionPeriod, attribute
from folio.analytics.lookthrough import Exposure, Holdings, Wrapper, aggregate, expand
from folio.analytics.returns import DailyPoint, ReturnFigures, return_figures, twr_index
from folio.analytics.risk import (
    Drawdown,
    RiskFigures,
    correlation_matrix,
    daily_returns,
    drawdown,
    risk_figures,
)
from folio.analytics.series import rebase
from folio.analytics.valuation import DayPoint, resolve_period
from folio.db.models import Account
from folio.db.models_analytics import Sleeve
from folio.db.models_ledger import (
    FxRate,
    Instrument,
    LedgerTransaction,
    Listing,
    PriceBar,
)
from folio.lookthrough.service import latest_snapshots
from folio.marketdata.macro import DEPOSIT_RATE, MacroService
from folio.portfolio import InstrumentAt, Valuation
from folio.settings_schema import AnalyticsSettings
from folio.settings_store import load_section

_T = TypeVar("_T")
ZERO = Decimal(0)
_NOTHING = InstrumentAt(ZERO, ZERO, ZERO)
CACHE_SIZE = 4


@dataclass
class AnalyticsContext:
    days: list[date]  # ascending; the first is the day before the first transaction
    points: list[DayPoint]  # the portfolio on each day
    instruments: dict[int, list[InstrumentAt]]  # per instrument ever held, aligned with days
    prices: dict[int, list[Decimal | None]]  # EUR close, aligned with days (held + extras)
    trading_days: frozenset[date]  # days on which a held instrument had a close
    tracks_cash: bool
    _memo: dict[object, object] = field(default_factory=dict, repr=False, compare=False)

    @property
    def empty(self) -> bool:
        return len(self.days) < 2

    @property
    def first_transaction_day(self) -> date | None:
        return None if self.empty else self.days[1]

    def cached(self, key: object, compute: Callable[[], _T]) -> _T:
        """Derived results (series, matrices) are computed once per context: the context is
        immutable, and a new one replaces it whenever the stored data change."""
        if key not in self._memo:
            self._memo[key] = compute()
        return self._memo[key]  # type: ignore[return-value]

    def index(self, day: date) -> int:
        """Position of the last context day on or before `day` (0 when it is before them all)."""
        return max(0, bisect_right(self.days, day) - 1)


EMPTY = AnalyticsContext([], [], {}, {}, frozenset(), False)


# --- building and caching -----------------------------------------------------------------------


def build_context(
    db: Session,
    today: date,
    account_id: int | None = None,
    extra_instrument_ids: Iterable[int] = (),
) -> AnalyticsContext:
    extras = set(extra_instrument_ids)
    valuation = Valuation.load(db, account_id=account_id, extra_instrument_ids=extras)
    first = valuation.first_date()
    if first is None or first > today:
        return EMPTY
    base = first - timedelta(days=1)
    wanted = {base, today} | valuation.transaction_dates()
    wanted |= {d for d in valuation.price_dates() if first <= d <= today}
    wanted |= {date(y, 1, 1) for y in range(first.year + 1, today.year + 1)}  # the peildatum
    days = sorted(d for d in wanted if base <= d <= today)

    points = [valuation.point(d) for d in days]
    per_day = [valuation.instrument_values(d) for d in days]
    held = {i for values in per_day for i in values}
    instruments = {i: [values.get(i, _NOTHING) for values in per_day] for i in sorted(held)}
    prices = {i: [valuation.eur_price(i, d) for d in days] for i in sorted(held | extras)}
    return AnalyticsContext(
        days=days,
        points=points,
        instruments=instruments,
        prices=prices,
        trading_days=frozenset(valuation.price_dates(held)),
        tracks_cash=valuation.tracks_cash,
    )


def data_fingerprint(db: Session) -> tuple[object, ...]:
    """Changes whenever stored data that analytics depend on changes. One cheap aggregate per
    table: row count, newest id and newest update."""

    def stamp(model: type, *, ids: bool = True) -> tuple[object, ...]:
        columns = [func.count(), func.max(model.updated_at)]  # type: ignore[attr-defined]
        if ids:
            columns.append(func.max(model.id))  # type: ignore[attr-defined]
        return tuple(db.execute(select(*columns)).one())

    return (
        stamp(LedgerTransaction),
        stamp(Account),
        stamp(Instrument),
        stamp(Listing),
        stamp(PriceBar),
        stamp(FxRate),
    )


_cache: OrderedDict[tuple[object, ...], AnalyticsContext] = OrderedDict()
_lock = threading.Lock()


def get_context(
    db: Session,
    today: date,
    account_id: int | None = None,
    extra_instrument_ids: Iterable[int] = (),
) -> AnalyticsContext:
    extras = tuple(sorted(set(extra_instrument_ids)))
    key = (data_fingerprint(db), account_id, extras, today)
    with _lock:
        found = _cache.get(key)
        if found is not None:
            _cache.move_to_end(key)
            return found
    context = build_context(db, today, account_id, extras)
    with _lock:
        _cache[key] = context
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return context


def clear_cache() -> None:
    with _lock:
        _cache.clear()


# --- series -------------------------------------------------------------------------------------


def portfolio_series(ctx: AnalyticsContext) -> list[DailyPoint]:
    """The whole portfolio as daily points. Income is net of standalone costs and counts only
    what is outside the value (cash-tracked accounts hold theirs inside it)."""
    return ctx.cached("portfolio_series", lambda: _portfolio_series(ctx))


def _portfolio_series(ctx: AnalyticsContext) -> list[DailyPoint]:
    out: list[DailyPoint] = []
    previous: DayPoint | None = None
    for day, point in zip(ctx.days, ctx.points, strict=True):
        if previous is None:
            out.append(DailyPoint(day, point.value_eur))
        else:
            net_now = point.outside_income_eur - point.outside_costs_eur
            net_before = previous.outside_income_eur - previous.outside_costs_eur
            out.append(
                DailyPoint(
                    day,
                    point.value_eur,
                    point.net_contributions_eur - previous.net_contributions_eur,
                    net_now - net_before,
                )
            )
        previous = point
    return out


def instrument_series(
    ctx: AnalyticsContext,
    instrument_ids: Iterable[int],
    start: date | None = None,
    end: date | None = None,
) -> list[DailyPoint]:
    """One or several instruments (a sleeve) as daily points. Unpriced days count as zero.
    With `start` and `end` only that stretch is built, from the baseline day before `start`."""
    ids = [i for i in instrument_ids if i in ctx.instruments]
    first = 0 if start is None else ctx.index(start)
    last = len(ctx.days) - 1 if end is None else ctx.index(end)
    out: list[DailyPoint] = []
    previous_invested = previous_income = ZERO
    for n in range(first, last + 1):
        day = ctx.days[n]
        value = sum((ctx.instruments[i][n].value or ZERO for i in ids), ZERO)
        invested = sum((ctx.instruments[i][n].net_invested_eur for i in ids), ZERO)
        income = sum((ctx.instruments[i][n].income_eur for i in ids), ZERO)
        if n == first:
            out.append(DailyPoint(day, value))
        else:
            out.append(
                DailyPoint(day, value, invested - previous_invested, income - previous_income)
            )
        previous_invested, previous_income = invested, income
    return out


def window(
    ctx: AnalyticsContext, series: Sequence[DailyPoint], start: date, end: date
) -> list[DailyPoint]:
    """The points from the baseline day (the last one on or before `start`) to `end`."""
    if ctx.empty:
        return []
    first, last = ctx.index(start), ctx.index(end)
    return list(series[first : last + 1])


def resolve(
    ctx: AnalyticsContext,
    period: str,
    today: date,
    custom_start: date | None = None,
    custom_end: date | None = None,
) -> tuple[date, date]:
    return resolve_period(period, today, ctx.first_transaction_day, custom_start, custom_end)


# --- returns ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ReturnsResult:
    start: date
    end: date
    figures: ReturnFigures | None
    value_start: Decimal
    value_end: Decimal
    net_flows: Decimal
    income: Decimal
    pnl: Decimal


def returns_for(points: Sequence[DailyPoint]) -> ReturnsResult | None:
    if len(points) < 2:
        return None
    flows = sum((p.flow for p in points[1:]), ZERO)
    income = sum((p.income for p in points[1:]), ZERO)
    start_value, end_value = points[0].value, points[-1].value
    return ReturnsResult(
        start=points[0].day,
        end=points[-1].day,
        figures=return_figures(points),
        value_start=start_value,
        value_end=end_value,
        net_flows=flows,
        income=income,
        pnl=end_value - start_value - flows + income,
    )


def instruments_in_sleeve(db: Session, sleeve_id: int) -> list[int]:
    return list(
        db.scalars(
            select(Instrument.id).where(
                Instrument.sleeve_id == sleeve_id, Instrument.deleted_at.is_(None)
            )
        )
    )


# --- history ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class HistoryRow:
    day: date
    value: Decimal
    net_contributions: Decimal
    twr_index: Decimal
    drawdown: Decimal
    unvalued: int
    is_peildatum: bool


def history(ctx: AnalyticsContext, start: date | None, end: date | None) -> list[HistoryRow]:
    """Value against net contributions with the time-weighted index and the drawdown, from the
    first transaction to `end` (FR-PF-02). The index is 1 at the start of the first day shown."""
    if ctx.empty:
        return []
    first = ctx.index(start) if start is not None else 1
    first = max(first, 1)
    last = ctx.index(end) if end is not None else len(ctx.days) - 1
    if last < first:
        return []
    series = portfolio_series(ctx)
    index = twr_index(series[first - 1 : last + 1])[1:]  # drop the baseline row
    under = drawdown(index).series
    rows = []
    for offset, ((day, level), (_, depth)) in enumerate(zip(index, under, strict=True)):
        point = ctx.points[first + offset]
        rows.append(
            HistoryRow(
                day,
                point.value_eur,
                point.net_contributions_eur,
                level,
                depth,
                point.unvalued,
                day.month == 1 and day.day == 1,
            )
        )
    return rows


# --- allocation ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class InstrumentMeta:
    id: int
    name: str
    asset_class: str
    region: str | None
    sector: str | None
    currency: str | None
    sleeve: str | None
    isin: str | None = None
    domicile: str | None = None


def load_meta(db: Session, ids: Iterable[int] | None = None) -> dict[int, InstrumentMeta]:
    query = select(Instrument).where(Instrument.deleted_at.is_(None))
    if ids is not None:
        query = query.where(Instrument.id.in_(set(ids)))
    sleeves = {s.id: s.name for s in db.scalars(select(Sleeve))}
    meta: dict[int, InstrumentMeta] = {}
    for instrument in db.scalars(query):
        listing = db.scalars(
            select(Listing)
            .where(Listing.instrument_id == instrument.id)
            .order_by(Listing.pricing_primary.desc(), Listing.id)
            .limit(1)
        ).first()
        meta[instrument.id] = InstrumentMeta(
            id=instrument.id,
            name=instrument.name,
            asset_class=instrument.asset_class,
            region=instrument.region,
            sector=instrument.sector,
            currency=None if listing is None else listing.currency,
            sleeve=None if instrument.sleeve_id is None else sleeves.get(instrument.sleeve_id),
            isin=instrument.isin,
            domicile=instrument.domicile,
        )
    return meta


def group_key(meta: InstrumentMeta | None, group_by: str) -> str:
    if meta is None:
        return UNCLASSIFIED
    if group_by == "instrument":
        return meta.name
    value = {
        "asset_class": meta.asset_class,
        "sleeve": meta.sleeve,
        "region": meta.region,
        "sector": meta.sector,
        "currency": meta.currency,
    }[group_by]
    return value or UNCLASSIFIED


def sleeve_targets(db: Session) -> dict[str, tuple[Decimal, Decimal | None]]:
    """Targets and bands as fractions, only for sleeves that have a target (Q3)."""
    targets: dict[str, tuple[Decimal, Decimal | None]] = {}
    for sleeve in db.scalars(select(Sleeve).where(Sleeve.deleted_at.is_(None))):
        if sleeve.target_pct is not None:
            band = None if sleeve.band_pct is None else sleeve.band_pct / 100
            targets[sleeve.name] = (sleeve.target_pct / 100, band)
    return targets


def allocation_at(
    db: Session, ctx: AnalyticsContext, day: date, group_by: str
) -> tuple[Allocation, int]:
    """Allocation of the portfolio's valued holdings on `day`, and how many holdings were left
    out for lack of a price."""
    if ctx.empty:
        return allocate([]), 0
    point = ctx.points[ctx.index(day)]
    meta = load_meta(db, {h.instrument_id for h in point.holdings})
    holdings = [
        (group_key(meta.get(h.instrument_id), group_by), h.value_eur)
        for h in point.holdings
        if h.value_eur is not None
    ]
    targets = sleeve_targets(db) if group_by == "sleeve" else None
    return allocate(holdings, targets), point.unvalued


# --- look-through (FR-PF-05) --------------------------------------------------------------------

FUNDS = ("ETF", "ETC", "FUND")


@dataclass(frozen=True)
class LookThrough:
    as_of: date
    dimension: str
    total_eur: Decimal  # the valued positions that were looked at
    exposures: list[Exposure]
    opened: list[tuple[str, date]]  # positions opened up, with the date of their holdings
    unopened: list[str]  # funds held without holdings data: shown as themselves
    unvalued: int


def wrappers_for(
    values: Iterable[tuple[int, Decimal]], meta: dict[int, InstrumentMeta]
) -> list[Wrapper]:
    """The positions to look through, from (instrument, euro value) pairs."""
    out: list[Wrapper] = []
    for instrument_id, value in values:
        m = meta.get(instrument_id)
        out.append(
            Wrapper(
                instrument_id=instrument_id,
                name=m.name if m else f"Instrument {instrument_id}",
                isin=None if m is None else m.isin,
                value_eur=value,
                sector=None if m is None else m.sector,
                # an ISIN's country is the issuer's for a share; for a fund it is the fund's
                country=m.domicile if m is not None and m.asset_class == "EQUITY" else None,
                currency=None if m is None else m.currency,
                is_fund=m is not None and m.asset_class in FUNDS,
            )
        )
    return out


def holdings_for(db: Session, wrappers: Sequence[Wrapper], day: date) -> dict[int, Holdings]:
    """The newest holdings snapshot, on or before `day`, of each position that has one."""
    snapshots = latest_snapshots(db, [w.instrument_id for w in wrappers], on=day)
    return {i: Holdings(s.covered_pct, s.constituents) for i, s in snapshots.items()}


def look_through_at(db: Session, ctx: AnalyticsContext, day: date, dimension: str) -> LookThrough:
    """The portfolio on `day` opened up into what it holds: ETFs with a holdings snapshot become
    their constituents, everything else stays itself."""
    if ctx.empty:
        return LookThrough(day, dimension, ZERO, [], [], [], 0)
    point = ctx.points[ctx.index(day)]
    meta = load_meta(db, {h.instrument_id for h in point.holdings})
    wrappers = wrappers_for(
        ((h.instrument_id, h.value_eur) for h in point.holdings if h.value_eur is not None), meta
    )
    snapshots = latest_snapshots(db, [w.instrument_id for w in wrappers], on=day)
    holdings = {i: Holdings(s.covered_pct, s.constituents) for i, s in snapshots.items()}
    names = {w.instrument_id: w.name for w in wrappers}
    return LookThrough(
        as_of=day,
        dimension=dimension,
        total_eur=sum((w.value_eur for w in wrappers), ZERO),
        exposures=aggregate(expand(wrappers, holdings), dimension),
        opened=[(names[i], snapshots[i].as_of) for i in holdings],
        unopened=[
            w.name
            for w in wrappers
            if w.instrument_id not in holdings
            and (m := meta.get(w.instrument_id)) is not None
            and m.asset_class in FUNDS
        ],
        unvalued=point.unvalued,
    )


# --- risk ---------------------------------------------------------------------------------------


def risk_free_rate(db: Session, on: date) -> Decimal:
    """The annual risk-free rate as a fraction: the owner's fixed figure, or the ECB deposit
    facility rate once that series is stored."""
    settings = AnalyticsSettings.model_validate(load_section(db, "analytics").model_dump())
    fixed = settings.risk_free_fixed_pct / 100
    if settings.risk_free_source == "fixed":
        return fixed
    return deposit_rate(db, on) or fixed


def deposit_rate(db: Session, on: date) -> Decimal | None:
    """ECB deposit facility rate in force on `on` as a fraction, or None while the series is
    not stored."""
    percent = MacroService(db).value_on(DEPOSIT_RATE, on)
    return None if percent is None else percent / 100


@dataclass(frozen=True)
class RiskResult:
    start: date
    end: date
    figures: RiskFigures
    drawdown: Drawdown
    risk_free: Decimal
    benchmark_id: int | None


def risk_for(
    db: Session,
    ctx: AnalyticsContext,
    start: date,
    end: date,
    benchmark_id: int | None = None,
) -> RiskResult | None:
    points = window(ctx, portfolio_series(ctx), start, end)
    if len(points) < 2:
        return None
    index = twr_index(points)
    benchmark_returns = None
    if benchmark_id is not None and benchmark_id in ctx.prices:
        benchmark_returns = _price_returns(ctx, benchmark_id, start, end)
    rate = risk_free_rate(db, end)
    figures = risk_figures(index, set(ctx.trading_days), rate, benchmark_returns)
    return RiskResult(points[0].day, points[-1].day, figures, drawdown(index), rate, benchmark_id)


def _price_returns(
    ctx: AnalyticsContext, instrument_id: int, start: date, end: date
) -> list[tuple[date, Decimal]]:
    return ctx.cached(
        ("price_returns", instrument_id, start, end),
        lambda: _compute_price_returns(ctx, instrument_id, start, end),
    )


def _compute_price_returns(
    ctx: AnalyticsContext, instrument_id: int, start: date, end: date
) -> list[tuple[date, Decimal]]:
    first, last = ctx.index(start), ctx.index(end)
    series = [
        (ctx.days[n], price)
        for n, price in enumerate(ctx.prices[instrument_id][first : last + 1], start=first)
        if price is not None
    ]
    return daily_returns(series, set(ctx.trading_days))


def correlations(
    ctx: AnalyticsContext, start: date, end: date, instrument_ids: Sequence[int]
) -> dict[int, dict[int, Decimal | None]]:
    ids = tuple(i for i in instrument_ids if i in ctx.prices)
    return ctx.cached(
        ("correlations", ids, start, end),
        lambda: correlation_matrix({i: _price_returns(ctx, i, start, end) for i in ids}),
    )


def held_instruments(ctx: AnalyticsContext, day: date) -> list[int]:
    if ctx.empty:
        return []
    n = ctx.index(day)
    return [h.instrument_id for h in ctx.points[n].holdings if h.value_eur is not None]


# --- attribution --------------------------------------------------------------------------------

OTHER = "other"


@dataclass(frozen=True)
class AttributionResult:
    start: date
    end: date
    attribution: Attribution
    other_pnl_eur: Decimal
    portfolio_pnl_eur: Decimal


def attribution_for(ctx: AnalyticsContext, start: date, end: date) -> AttributionResult | None:
    if ctx.empty:
        return None
    first, last = ctx.index(start), ctx.index(end)
    if last <= first:
        return None
    items: list[PositionPeriod] = []
    for instrument_id, states in ctx.instruments.items():
        a, b = states[first], states[last]
        value_start, value_end = a.value or ZERO, b.value or ZERO
        flows = b.net_invested_eur - a.net_invested_eur
        income = b.income_eur - a.income_eur
        if value_start == 0 and value_end == 0 and flows == 0 and income == 0:
            continue
        items.append(PositionPeriod(instrument_id, value_start, value_end, flows, income))
    portfolio = portfolio_series(ctx)
    flow_days = [(p.day, p.flow) for p in portfolio[first + 1 : last + 1] if p.flow != 0]
    start_point, end_point = ctx.points[first], ctx.points[last]
    portfolio_pnl = (
        (end_point.value_eur - start_point.value_eur)
        - (end_point.net_contributions_eur - start_point.net_contributions_eur)
        + (end_point.outside_income_eur - start_point.outside_income_eur)
        - (end_point.outside_costs_eur - start_point.outside_costs_eur)
    )
    positions_pnl = sum((i.value_end - i.value_start - i.flows + i.income for i in items), ZERO)
    other = portfolio_pnl - positions_pnl  # costs, interest, anything not tied to a position
    # the "other" line is a pure result: it started and ended at zero, with the result as income
    all_items = items + [PositionPeriod(OTHER, ZERO, ZERO, ZERO, other)]
    return AttributionResult(
        ctx.days[first],
        ctx.days[last],
        attribute(all_items, ctx.days[first], ctx.days[last], flow_days),
        other,
        portfolio_pnl,
    )


# --- benchmarks ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class RebasedSeries:
    key: str  # "portfolio" or the benchmark's instrument id
    points: list[tuple[date, Decimal]]


def benchmark_series(
    ctx: AnalyticsContext, benchmark_ids: Sequence[int], start: date, end: date
) -> list[RebasedSeries]:
    """The portfolio's time-weighted index and each benchmark's EUR price, all 100 at `start`."""
    if ctx.empty:
        return []
    hundred = Decimal(100)
    points = window(ctx, portfolio_series(ctx), start, end)
    out = [RebasedSeries("portfolio", [(day, level * hundred) for day, level in twr_index(points)])]
    first, last = ctx.index(start), ctx.index(end)
    for benchmark_id in benchmark_ids:
        prices = ctx.prices.get(benchmark_id)
        if prices is None:
            continue
        series = [
            (ctx.days[n], p)
            for n, p in enumerate(prices[first : last + 1], start=first)
            if p is not None
        ]
        out.append(RebasedSeries(str(benchmark_id), rebase(series, ctx.days[first])))
    return out


def benchmark_ids(db: Session, limit: int = 3) -> list[int]:
    return list(
        db.scalars(
            select(Instrument.id)
            .where(Instrument.is_benchmark.is_(True), Instrument.deleted_at.is_(None))
            .order_by(Instrument.id)
            .limit(limit)
        )
    )
