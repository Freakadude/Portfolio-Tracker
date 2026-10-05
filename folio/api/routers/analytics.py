"""Analytics endpoints under /portfolio: returns, allocation, risk, attribution, benchmarks and
the what-if simulator (FR-PF-03, 04, 06, 07, 08, 09; FR-MD-12)."""

import datetime as dt
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from folio import analytics_service as svc
from folio.analytics.allocation import GROUPINGS, Allocation, allocate
from folio.analytics.lookthrough import DIMENSIONS, Exposure, Part, aggregate, expand
from folio.analytics.returns import DailyPoint
from folio.analytics.simulate import SimulationError, Trade, simulate
from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.db.models import Account
from folio.db.models_ledger import Instrument

router = APIRouter(prefix="/portfolio", tags=["analytics"])

FromParam = Annotated[date | None, Query(alias="from")]


# --- shared -------------------------------------------------------------------------------------


class PartOut(BaseModel):
    """Where part of a look-through exposure sits: a direct holding or inside an ETF."""

    source: str
    instrument_id: int
    kind: Literal["direct", "look_through", "fund", "other"]
    value_eur: Decimal
    weight_pct: Decimal | None  # the constituent's weight inside the ETF


class SliceOut(BaseModel):
    key: str
    value_eur: Decimal
    weight: Decimal
    target: Decimal | None
    drift_pp: Decimal | None  # actual minus target, as a fraction of the portfolio
    drift_relative: Decimal | None
    outside_band: bool | None
    parts: list[PartOut] = Field(default_factory=list)  # look-through only


class AllocationOut(BaseModel):
    group_by: str
    as_of: dt.date
    total_eur: Decimal
    unvalued_positions: int
    slices: list[SliceOut]
    look_through: bool = False
    unopened: list[str] = Field(default_factory=list)  # funds held without holdings data


def _allocation_out(
    allocation: Allocation, group_by: str, as_of: date, unvalued: int
) -> AllocationOut:
    return AllocationOut(
        group_by=group_by,
        as_of=as_of,
        total_eur=allocation.total_eur,
        unvalued_positions=unvalued,
        slices=[
            SliceOut(
                key=s.key,
                value_eur=s.value_eur,
                weight=s.weight,
                target=None if s.drift is None else s.drift.target,
                drift_pp=None if s.drift is None else s.drift.pp,
                drift_relative=None if s.drift is None else s.drift.relative,
                outside_band=None if s.drift is None else s.drift.outside_band,
            )
            for s in allocation.slices
        ],
    )


def _check_account(db: Session, account: int | None) -> None:
    if account is None:
        return
    found = db.get(Account, account)
    if found is None or found.deleted_at is not None:
        raise ApiError(404, "Not found", "That account does not exist.")


def _context(
    db: Session, today: date, account: int | None, extras: list[int] | None = None
) -> svc.AnalyticsContext:
    _check_account(db, account)
    return svc.get_context(db, today, account, extras or ())


def _period(
    ctx: svc.AnalyticsContext, period: str, today: date, start: date | None, end: date | None
) -> tuple[date, date]:
    try:
        return svc.resolve(ctx, period, today, start, end)
    except ValueError as exc:
        raise ApiError(422, "Invalid period", str(exc)) from exc


# --- returns ------------------------------------------------------------------------------------


class ReturnsOut(BaseModel):
    scope: str
    start: dt.date
    end: dt.date
    twr: Decimal | None
    twr_annualised: Decimal | None
    xirr: Decimal | None
    pnl_eur: Decimal
    value_start_eur: Decimal
    value_end_eur: Decimal
    net_flows_eur: Decimal
    income_eur: Decimal


def _parse_scope(scope: str) -> tuple[str, int | None]:
    kind, _, raw = scope.partition(":")
    if kind == "portfolio" and not raw:
        return kind, None
    if kind in ("account", "sleeve", "instrument") and raw.isdigit():
        return kind, int(raw)
    raise ApiError(
        422,
        "Invalid scope",
        "Use portfolio, account:ID, sleeve:ID or instrument:ID, for example sleeve:3.",
    )


def _returns_out(scope: str, points: list[DailyPoint]) -> ReturnsOut:
    result = svc.returns_for(points)
    if result is None:
        raise ApiError(
            404, "No data", "There is nothing to measure yet: no transactions in this period."
        )
    figures = result.figures
    return ReturnsOut(
        scope=scope,
        start=result.start,
        end=result.end,
        twr=None if figures is None else figures.twr,
        twr_annualised=None if figures is None else figures.twr_annualised,
        xirr=None if figures is None else figures.xirr,
        pnl_eur=result.pnl,
        value_start_eur=result.value_start,
        value_end_eur=result.value_end,
        net_flows_eur=result.net_flows,
        income_eur=result.income,
    )


@router.get("/returns", response_model=ReturnsOut)
def returns(
    _user: UserDep,
    db: DbDep,
    period: str = "1Y",
    scope: str = "portfolio",
    as_of: date | None = None,
    from_: FromParam = None,
    to: date | None = None,
    account: int | None = None,
) -> ReturnsOut:
    """Time-weighted and money-weighted return of the portfolio, an account, a sleeve or one
    instrument over a period (FR-PF-03)."""
    today = as_of or date.today()
    kind, ident = _parse_scope(scope)
    ctx = _context(db, today, ident if kind == "account" else account)
    start, end = _period(ctx, period, today, from_, to)
    if kind in ("portfolio", "account"):
        series = svc.portfolio_series(ctx)
        return _returns_out(scope, svc.window(ctx, series, start, end))
    if kind == "sleeve" and ident is not None:
        ids = svc.instruments_in_sleeve(db, ident)
    elif ident is not None:
        ids = [ident]
    else:  # unreachable: _parse_scope guarantees an id for these kinds
        raise ApiError(422, "Invalid scope", scope)
    return _returns_out(scope, svc.instrument_series(ctx, ids, start, end))


class InstrumentReturnOut(BaseModel):
    instrument_id: int
    name: str
    twr: Decimal | None
    xirr: Decimal | None
    pnl_eur: Decimal
    value_start_eur: Decimal
    value_end_eur: Decimal


@router.get("/returns/instruments", response_model=list[InstrumentReturnOut])
def instrument_returns(
    _user: UserDep,
    db: DbDep,
    period: str = "1Y",
    as_of: date | None = None,
    from_: FromParam = None,
    to: date | None = None,
    account: int | None = None,
) -> list[InstrumentReturnOut]:
    """Return and result of every position that was held in the period (heatmap, FR-PF-03)."""
    today = as_of or date.today()
    ctx = _context(db, today, account)
    if ctx.empty:
        return []
    start, end = _period(ctx, period, today, from_, to)
    meta = svc.load_meta(db, ctx.instruments)
    out: list[InstrumentReturnOut] = []
    for instrument_id in ctx.instruments:
        result = svc.returns_for(svc.instrument_series(ctx, [instrument_id], start, end))
        if result is None or (
            result.value_start == 0 and result.value_end == 0 and result.pnl == 0
        ):
            continue
        figures = result.figures
        out.append(
            InstrumentReturnOut(
                instrument_id=instrument_id,
                name=meta[instrument_id].name if instrument_id in meta else str(instrument_id),
                twr=None if figures is None else figures.twr,
                xirr=None if figures is None else figures.xirr,
                pnl_eur=result.pnl,
                value_start_eur=result.value_start,
                value_end_eur=result.value_end,
            )
        )
    return sorted(out, key=lambda r: -r.value_end_eur)


# --- allocation ---------------------------------------------------------------------------------


def _part_out(part: Part) -> PartOut:
    return PartOut(
        source=part.source,
        instrument_id=part.instrument_id,
        kind=part.kind,
        value_eur=part.value_eur,
        weight_pct=part.weight_pct,
    )


def _exposure_slice(e: Exposure) -> SliceOut:
    return SliceOut(
        key=e.label,
        value_eur=e.value_eur,
        weight=e.weight,
        target=None,
        drift_pp=None,
        drift_relative=None,
        outside_band=None,
        parts=[_part_out(p) for p in e.parts],
    )


@router.get("/allocation", response_model=AllocationOut)
def allocation(
    _user: UserDep,
    db: DbDep,
    group_by: Literal[
        "instrument", "asset_class", "sleeve", "region", "sector", "currency", "company", "country"
    ] = "asset_class",
    look_through: bool = False,
    account: int | None = None,
    as_of: date | None = None,
) -> AllocationOut:
    """What the portfolio holds, by instrument, asset class, sleeve, region, sector or currency,
    with drift from the sleeve targets where there are any (FR-PF-04). With `look_through`,
    ETFs are opened up into what they hold and the grouping is company, sector, country or
    currency (FR-PF-05)."""
    today = as_of or date.today()
    ctx = _context(db, today, account)
    if look_through:
        if group_by not in DIMENSIONS:
            raise ApiError(
                422,
                "Cannot look through",
                "Look-through groups by company, sector, country or currency.",
            )
        opened = svc.look_through_at(db, ctx, today, group_by)
        return AllocationOut(
            group_by=group_by,
            as_of=today,
            total_eur=opened.total_eur,
            unvalued_positions=opened.unvalued,
            slices=[_exposure_slice(e) for e in opened.exposures],
            look_through=True,
            unopened=opened.unopened,
        )
    if group_by in ("company", "country"):
        raise ApiError(
            422, "Needs look-through", f"Grouping by {group_by} needs look_through=true."
        )
    assert group_by in GROUPINGS  # noqa: S101 - the Literal above is the validation
    result, unvalued = svc.allocation_at(db, ctx, today, group_by)
    return _allocation_out(result, group_by, today, unvalued)


class OpenedOut(BaseModel):
    name: str
    holdings_as_of: dt.date


class LookThroughOut(BaseModel):
    as_of: dt.date
    dimension: str
    total_eur: Decimal
    exposures: list[SliceOut]  # the largest `top`, each with where it comes from
    rest_weight: Decimal  # everything below the top, as a fraction of the portfolio
    opened: list[OpenedOut]  # the positions that were opened up
    unopened: list[str]  # funds held without holdings data, shown as themselves
    unvalued_positions: int


@router.get("/look-through", response_model=LookThroughOut)
def look_through(
    _user: UserDep,
    db: DbDep,
    dimension: Literal["company", "sector", "country", "currency"] = "company",
    top: Annotated[int, Query(ge=1, le=100)] = 20,
    account: int | None = None,
    as_of: date | None = None,
) -> LookThroughOut:
    """The largest underlying exposures across direct holdings and ETFs, each with the
    positions it sits in (FR-PF-05)."""
    today = as_of or date.today()
    opened = svc.look_through_at(db, _context(db, today, account), today, dimension)
    shown = opened.exposures[:top]
    return LookThroughOut(
        as_of=today,
        dimension=dimension,
        total_eur=opened.total_eur,
        exposures=[_exposure_slice(e) for e in shown],
        rest_weight=sum((e.weight for e in opened.exposures[top:]), Decimal(0)),
        opened=[OpenedOut(name=n, holdings_as_of=d) for n, d in opened.opened],
        unopened=opened.unopened,
        unvalued_positions=opened.unvalued,
    )


# --- risk ---------------------------------------------------------------------------------------

WINDOWS = {"90D": 90, "1Y": 365, "3Y": 3 * 365, "MAX": 0}


class DrawdownPoint(BaseModel):
    date: dt.date
    value: Decimal


class MatrixOut(BaseModel):
    window: str
    instruments: list[int]
    labels: list[str]
    values: list[list[Decimal | None]]


class RiskOut(BaseModel):
    start: dt.date
    end: dt.date
    window: str
    volatility: Decimal | None
    annual_return: Decimal | None
    sharpe: Decimal | None
    beta: Decimal | None
    benchmark_id: int | None
    risk_free: Decimal
    max_drawdown: Decimal
    max_drawdown_start: dt.date | None
    max_drawdown_end: dt.date | None
    current_drawdown: Decimal
    drawdown: list[DrawdownPoint]
    correlations: list[MatrixOut]


@router.get("/risk", response_model=RiskOut)
def risk(
    _user: UserDep,
    db: DbDep,
    window: Literal["90D", "1Y", "3Y", "MAX"] = "1Y",
    benchmark: int | None = None,
    account: int | None = None,
    as_of: date | None = None,
) -> RiskOut:
    """Volatility, drawdowns, Sharpe, beta and the correlation matrices (FR-PF-06)."""
    today = as_of or date.today()
    extras = [benchmark] if benchmark is not None else []
    ctx = _context(db, today, account, extras)
    if ctx.empty:
        raise ApiError(404, "No data", "There is nothing to measure yet: no transactions.")
    days = WINDOWS[window]
    start = ctx.days[0] if days == 0 else today - dt.timedelta(days=days)
    result = svc.risk_for(db, ctx, start, today, benchmark)
    if result is None:
        raise ApiError(404, "No data", "There is nothing to measure in this window.")
    held = svc.held_instruments(ctx, today)
    meta = svc.load_meta(db, held)
    matrices: list[MatrixOut] = []
    for label, span in (("90D", 90), ("1Y", 365)):
        ids = [i for i in held if i in meta]
        matrix = svc.correlations(ctx, today - dt.timedelta(days=span), today, ids)
        matrices.append(
            MatrixOut(
                window=label,
                instruments=ids,
                labels=[meta[i].name for i in ids],
                values=[[matrix[a].get(b) for b in ids] for a in ids],
            )
        )
    figures = result.figures
    return RiskOut(
        start=result.start,
        end=result.end,
        window=window,
        volatility=figures.volatility,
        annual_return=figures.annual_return,
        sharpe=figures.sharpe,
        beta=figures.beta,
        benchmark_id=result.benchmark_id,
        risk_free=result.risk_free,
        max_drawdown=figures.max_drawdown,
        max_drawdown_start=result.drawdown.maximum_start,
        max_drawdown_end=result.drawdown.maximum_end,
        current_drawdown=figures.current_drawdown,
        drawdown=[DrawdownPoint(date=d, value=v) for d, v in result.drawdown.series],
        correlations=matrices,
    )


# --- attribution --------------------------------------------------------------------------------


class ContributionOut(BaseModel):
    key: str  # an instrument id, or "other"
    name: str
    pnl_eur: Decimal
    points: Decimal | None  # share of the return, as a fraction (0.01 = one point)


class AttributionOut(BaseModel):
    start: dt.date
    end: dt.date
    portfolio_pnl_eur: Decimal
    total_return: Decimal | None  # the Modified Dietz return the points add up to
    capital_eur: Decimal
    contributions: list[ContributionOut]


@router.get("/attribution", response_model=AttributionOut)
def attribution(
    _user: UserDep,
    db: DbDep,
    period: str = "1Y",
    account: int | None = None,
    as_of: date | None = None,
    from_: FromParam = None,
    to: date | None = None,
) -> AttributionOut:
    """What each position contributed to the period's result, in euro and in points (FR-PF-07)."""
    today = as_of or date.today()
    ctx = _context(db, today, account)
    start, end = _period(ctx, period, today, from_, to)
    result = svc.attribution_for(ctx, start, end)
    if result is None:
        raise ApiError(404, "No data", "Nothing happened in this period to attribute.")
    meta = svc.load_meta(db, ctx.instruments)
    rows = []
    for c in result.attribution.contributions:
        name = (
            "Other (costs and interest)"
            if c.key == svc.OTHER
            else meta[int(c.key)].name
            if int(c.key) in meta
            else str(c.key)
        )
        rows.append(ContributionOut(key=str(c.key), name=name, pnl_eur=c.pnl_eur, points=c.points))
    rows.sort(key=lambda r: -abs(r.pnl_eur))
    return AttributionOut(
        start=result.start,
        end=result.end,
        portfolio_pnl_eur=result.portfolio_pnl_eur,
        total_return=result.attribution.total_return,
        capital_eur=result.attribution.capital,
        contributions=rows,
    )


# --- benchmarks ---------------------------------------------------------------------------------


class SeriesPoint(BaseModel):
    date: dt.date
    value: Decimal


class SeriesOut(BaseModel):
    key: str
    label: str
    points: list[SeriesPoint]


class BenchmarksOut(BaseModel):
    start: dt.date
    end: dt.date
    series: list[SeriesOut]


@router.get("/benchmarks", response_model=BenchmarksOut)
def benchmarks(
    _user: UserDep,
    db: DbDep,
    ids: Annotated[list[int] | None, Query()] = None,
    period: str = "1Y",
    account: int | None = None,
    as_of: date | None = None,
    from_: FromParam = None,
    to: date | None = None,
) -> BenchmarksOut:
    """The portfolio and up to three benchmarks, all 100 at the start of the period (FR-PF-08).
    Without `ids`, the instruments flagged as benchmarks are used."""
    today = as_of or date.today()
    chosen = (ids if ids is not None else svc.benchmark_ids(db))[:3]
    if ids is not None and len(ids) > 3:
        raise ApiError(422, "Too many benchmarks", "Compare against at most three benchmarks.")
    ctx = _context(db, today, account, chosen)
    start, end = _period(ctx, period, today, from_, to)
    rebased = svc.benchmark_series(ctx, chosen, start, end)
    if not rebased:
        raise ApiError(404, "No data", "There is nothing to compare yet: no transactions.")
    meta = svc.load_meta(db, chosen)
    out = []
    for s in rebased:
        label = "Portfolio" if s.key == "portfolio" else meta[int(s.key)].name
        out.append(
            SeriesOut(
                key=s.key,
                label=label,
                points=[SeriesPoint(date=d, value=v) for d, v in s.points],
            )
        )
    return BenchmarksOut(start=rebased[0].points[0][0], end=rebased[0].points[-1][0], series=out)


# --- simulator ----------------------------------------------------------------------------------


class SimTradeIn(BaseModel):
    instrument_id: int
    side: Literal["buy", "sell"]
    quantity: Decimal = Field(gt=0)
    price_eur: Decimal | None = Field(default=None, gt=0)  # default: the latest close
    fees_eur: Decimal = Field(default=Decimal(0), ge=0)


class SimulateIn(BaseModel):
    trades: list[SimTradeIn] = Field(min_length=1, max_length=50)
    group_by: Literal["instrument", "asset_class", "sleeve", "region", "sector", "currency"] = (
        "asset_class"
    )
    account: int | None = None
    as_of: date | None = None


class SimPositionOut(BaseModel):
    instrument_id: int
    name: str
    quantity_before: Decimal
    quantity_after: Decimal
    value_before_eur: Decimal
    value_after_eur: Decimal


class CompanyChangeOut(BaseModel):
    """One underlying company's exposure before and after the trades (FR-PF-09)."""

    key: str
    label: str
    before_eur: Decimal
    after_eur: Decimal
    before_weight: Decimal
    after_weight: Decimal


class SimulationOut(BaseModel):
    as_of: dt.date
    cash_needed_eur: Decimal  # positive: money to find; negative: money freed
    before: AllocationOut
    after: AllocationOut
    positions: list[SimPositionOut]
    look_through: list[CompanyChangeOut] = Field(default_factory=list)  # empty: no ETF holdings


SHIFT_ROWS = 15


def _look_through_shift(
    db: Session, meta: dict[int, svc.InstrumentMeta], positions: Sequence[Any], day: date
) -> list[CompanyChangeOut]:
    """Company exposure before and after a simulation, when any of the funds involved has
    holdings data; otherwise nothing, since an ETF would just stay itself."""
    before = svc.wrappers_for(
        [(p.instrument_id, p.value_before_eur) for p in positions if p.value_before_eur > 0], meta
    )
    after = svc.wrappers_for(
        [(p.instrument_id, p.value_after_eur) for p in positions if p.value_after_eur > 0], meta
    )
    holdings = svc.holdings_for(db, [*before, *after], day)
    if not holdings:
        return []
    then = {e.key: e for e in aggregate(expand(before, holdings), "company")}
    now = {e.key: e for e in aggregate(expand(after, holdings), "company")}
    rows = [
        CompanyChangeOut(
            key=key,
            label=(now.get(key) or then[key]).label,
            before_eur=then[key].value_eur if key in then else Decimal(0),
            after_eur=now[key].value_eur if key in now else Decimal(0),
            before_weight=then[key].weight if key in then else Decimal(0),
            after_weight=now[key].weight if key in now else Decimal(0),
        )
        for key in {*then, *now}
        if not (then.get(key) or now[key]).other
    ]
    rows.sort(key=lambda r: (-max(r.before_eur, r.after_eur), r.key))
    return rows[:SHIFT_ROWS]


@router.post("/simulate", response_model=SimulationOut)
def simulate_trades(body: SimulateIn, _user: UserDep, db: DbDep) -> SimulationOut:
    """Show the allocation, drift and cash need after hypothetical trades. Nothing is written:
    the simulation works on copies of the numbers (FR-PF-09)."""
    today = body.as_of or date.today()
    wanted = sorted({t.instrument_id for t in body.trades})
    found = {
        i.id: i
        for i in db.scalars(
            select(Instrument).where(Instrument.id.in_(wanted), Instrument.deleted_at.is_(None))
        )
    }
    missing = [i for i in wanted if i not in found]
    if missing:
        raise ApiError(404, "Not found", "One of the instruments does not exist.")
    ctx = _context(db, today, body.account, wanted)
    point = ctx.points[ctx.index(today)] if not ctx.empty else None
    quantities: dict[int, Decimal] = {}
    for h in point.holdings if point else ():
        quantities[h.instrument_id] = quantities.get(h.instrument_id, Decimal(0)) + h.quantity
    last = ctx.index(today) if not ctx.empty else 0
    market = {i: p[last] for i, p in ctx.prices.items() if p and p[last] is not None}
    trades: list[Trade] = []
    for t in body.trades:
        price = t.price_eur or market.get(t.instrument_id)
        if price is None:
            raise ApiError(
                422,
                "No price",
                f"{found[t.instrument_id].name} has no price yet. Enter the price to assume.",
            )
        sign = 1 if t.side == "buy" else -1
        trades.append(Trade(t.instrument_id, sign * t.quantity, price, t.fees_eur))
    try:
        result = simulate(quantities, {i: p for i, p in market.items() if p is not None}, trades)
    except SimulationError as exc:
        name = found[exc.instrument_id].name
        raise ApiError(
            422, "Not enough units", f"You hold {exc.held} of {name}; this sale needs {exc.wanted}."
        ) from exc

    meta = svc.load_meta(db, {p.instrument_id for p in result.positions})
    targets = svc.sleeve_targets(db) if body.group_by == "sleeve" else None

    def allocate_values(values: list[tuple[int, Decimal]]) -> Allocation:
        return allocate(
            [(svc.group_key(meta.get(i), body.group_by), v) for i, v in values if v != 0],
            targets,
        )

    before = allocate_values([(p.instrument_id, p.value_before_eur) for p in result.positions])
    after = allocate_values([(p.instrument_id, p.value_after_eur) for p in result.positions])
    shifts = _look_through_shift(db, meta, result.positions, today)
    return SimulationOut(
        as_of=today,
        cash_needed_eur=result.cash_needed_eur,
        before=_allocation_out(before, body.group_by, today, 0),
        after=_allocation_out(after, body.group_by, today, 0),
        look_through=shifts,
        positions=[
            SimPositionOut(
                instrument_id=p.instrument_id,
                name=meta[p.instrument_id].name
                if p.instrument_id in meta
                else str(p.instrument_id),
                quantity_before=p.quantity_before,
                quantity_after=p.quantity_after,
                value_before_eur=p.value_before_eur,
                value_after_eur=p.value_after_eur,
            )
            for p in result.positions
        ],
    )
