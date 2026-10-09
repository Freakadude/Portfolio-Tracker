"""The data behind each widget (FR-DB-03, FR-DB-05). One function per widget type; each takes
the widget's validated options and the dashboard's filters and returns plain JSON (decimals as
strings). They all read the shared analytics context, so a dashboard with many widgets does the
heavy work once."""

from __future__ import annotations

import calendar
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio import analytics_service as svc
from folio.agent.budget import agent_settings
from folio.analytics.lookthrough import DIMENSIONS, Exposure
from folio.analytics.returns import DailyPoint, twr_index, twr_segments, xirr_flow_rows
from folio.analytics.risk import drawdown
from folio.analytics.series import bridge, monthly_returns, rebase
from folio.dashboards.widgets import WIDGET_TYPES, BaseConfig
from folio.db.models_analytics import MacroPoint, MacroSeries, Quote
from folio.db.models_insight import NewsAssessment, NewsCluster, NewsLink, Recommendation
from folio.db.models_ledger import Instrument, LedgerTransaction, Listing, PriceBar
from folio.db.models_strategy import Signal
from folio.display import two as display_two
from folio.marketdata import exchanges
from folio.marketdata.quotes import newer_quote
from folio.positions import load_positions, totals_for

ZERO = Decimal(0)
SPARK_POINTS = 60
CHART_POINTS = 800


class WidgetDataError(ValueError):
    """The widget cannot be drawn with these options; the message says what to change."""


@dataclass(frozen=True)
class Filters:
    period: str | None = None
    account: int | None = None
    start: date | None = None  # for a CUSTOM period
    end: date | None = None
    types: tuple[str, ...] = ()  # asset classes to look at (ETF, STOCK, ...)
    instruments: tuple[int, ...] = ()  # or these holdings; with both, either one counts


@dataclass
class Env:
    db: Session
    today: date
    filters: Filters


def s(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def thin(items: Sequence[Any], limit: int) -> list[Any]:
    """At most `limit` items, evenly spread, always keeping the first and the last."""
    if len(items) <= limit:
        return list(items)
    step = (len(items) - 1) / (limit - 1)
    picked = {round(i * step) for i in range(limit)} | {0, len(items) - 1}
    return [items[i] for i in sorted(picked)]


# --- options ------------------------------------------------------------------------------------


def period_of(cfg: BaseConfig, env: Env, default: str = "YTD") -> str:
    if cfg.period is not None:
        return cfg.period
    if cfg.follow_filters and env.filters.period:
        return env.filters.period
    return default


def account_of(cfg: BaseConfig, env: Env) -> int | None:
    if cfg.scope.kind == "account":
        return cfg.scope.id
    return env.filters.account if cfg.follow_filters else None


def context(
    env: Env,
    account: int | None,
    extras: Sequence[int] = (),
    only: Sequence[int] | None = None,
) -> svc.AnalyticsContext:
    return svc.get_context(env.db, env.today, account, extras, only, live=True)


def only_of(cfg: BaseConfig, env: Env) -> list[int] | None:
    """The instruments the dashboard's type and holding filter lets through, or None when it is
    not set (or this widget ignores the dashboard's filters or looks at one thing)."""
    f = env.filters
    if not (f.types or f.instruments) or not cfg.follow_filters:
        return None
    if cfg.scope.kind in ("sleeve", "instrument"):
        return None
    ids = set(f.instruments)
    if f.types:
        ids.update(
            env.db.scalars(
                select(Instrument.id).where(
                    Instrument.asset_class.in_(f.types), Instrument.deleted_at.is_(None)
                )
            )
        )
    return sorted(ids)


def context_for(env: Env, cfg: BaseConfig, extras: Sequence[int] = ()) -> svc.AnalyticsContext:
    """The analytics context of a widget: its account and the dashboard's type or holding
    filter. A filter that matches nothing you hold says so, instead of "add a transaction"."""
    only = only_of(cfg, env)
    ctx = context(env, account_of(cfg, env), extras, only)
    if only is not None and ctx.empty:
        raise WidgetDataError(
            "Nothing you hold matches the type or holding filter. Change it above the widgets."
        )
    return ctx


def window_of(ctx: svc.AnalyticsContext, period: str, env: Env) -> tuple[date, date]:
    try:
        return svc.resolve(ctx, period, env.today, env.filters.start, env.filters.end)
    except ValueError as exc:
        raise WidgetDataError(str(exc)) from exc


def series_for(
    env: Env, ctx: svc.AnalyticsContext, cfg: BaseConfig, start: date, end: date
) -> list[DailyPoint]:
    """The widget's scope as daily points over a window."""
    kind, ident = cfg.scope.kind, cfg.scope.id
    if kind in ("portfolio", "account"):
        return svc.window(ctx, svc.portfolio_series(ctx), start, end)
    if kind == "sleeve" and ident is not None:
        return svc.instrument_series(ctx, svc.instruments_in_sleeve(env.db, ident), start, end)
    if kind == "instrument" and ident is not None:
        return svc.instrument_series(ctx, [ident], start, end)
    raise WidgetDataError("Choose which sleeve or instrument this widget should show.")


def _empty(reason: str) -> dict[str, Any]:
    return {"empty": True, "reason": reason}


# --- KPI ----------------------------------------------------------------------------------------

_KINDS = {
    "value": "eur", "day_change": "eur", "total_return": "eur", "unrealized": "eur",
    "realized": "eur", "period_return": "eur",
    "twr": "pct", "xirr": "pct", "cash": "eur", "net_contributions": "eur", "income": "eur",
    "largest_drift": "pct", "volatility": "pct", "max_drawdown": "pct",
    "current_drawdown": "pct", "sharpe": "number", "beta": "number", "latest_price": "price",
}  # fmt: skip


# the figures a line of portfolio value says something about
_TRENDS = {
    "value",
    "total_return",
    "period_return",
    "twr",
    "xirr",
    "net_contributions",
    "day_change",
}


def _breakdown(metric: str, points: list[DailyPoint]) -> dict[str, Any]:
    """The steps behind a return figure, from the same series the figure is computed from, so
    the owner can follow it by hand or in a spreadsheet ("how is this calculated")."""
    if metric == "twr":
        return {
            "kind": "twr",
            "segments": [
                {
                    "start": g.start.isoformat(),
                    "end": g.end.isoformat(),
                    "flow": str(g.flow),
                    "start_capital": str(g.start_capital),
                    "end_value": str(g.end_value),
                    "income": str(g.income),
                    "ratio": str(g.ratio),
                }
                for g in twr_segments(points)
            ],
        }
    return {
        "kind": "xirr",
        "flows": [
            {"date": r.day.isoformat(), "amount": str(r.amount), "kind": r.kind}
            for r in xirr_flow_rows(points)
        ],
    }


def _latest_price(env: Env, cfg: Any, base: dict[str, Any]) -> dict[str, Any]:
    """The key figure "latest price" of one holding: the newest refresh price when it is from a
    later day than the newest close, else that close; with a chart of the day (1 day: the
    refresh prices of the latest session, from the close before it) or of the period."""
    if cfg.scope.kind != "instrument" or cfg.scope.id is None:
        return {
            **base,
            **_empty("Choose a holding (scope: Instrument) to see its latest price."),
        }
    instrument = env.db.get(Instrument, cfg.scope.id)
    if instrument is None or instrument.deleted_at is not None:
        raise WidgetDataError("That instrument no longer exists.")
    listing = _primary_listing(env, instrument.id)
    if listing is None:
        return {**base, **_empty("This instrument has no listing to price.")}
    bars = list(
        env.db.scalars(
            select(PriceBar)
            .where(PriceBar.listing_id == listing.id)
            .order_by(PriceBar.date.desc())
            .limit(2)
        )
    )
    last = bars[0] if bars else None
    quote = newer_quote(env.db, listing, last.date if last else date.min)
    if quote is not None:
        value, when = quote[0], exchanges.local_time(listing.exchange_mic, quote[1])
        label = f"Delayed price of {when:%Y-%m-%d %H:%M} ({quote[2]})"
    elif last is not None:
        value, label = last.close, f"Close of {last.date.isoformat()}"
    else:
        return {**base, **_empty("No prices are stored for this instrument yet.")}
    base.update(
        value=str(value),
        currency=listing.currency,
        instrument_id=instrument.id,
        name=instrument.name,
        label=label,
    )

    period = period_of(cfg, env)
    points: list[tuple[str, Decimal]] = []
    reference: Decimal | None = None
    if period == "1D":
        session = _session(env, listing)
        if session is None:
            reference = bars[1].close if len(bars) > 1 else None
            base["note"] = (
                "No refresh prices yet, so there is no chart of the day. They are fetched every "
                "15 minutes while the exchange is open, and only for what you hold or watch."
            )
        else:
            day, pairs, previous = session
            reference = previous
            points = ([("previous close", previous)] if previous is not None else []) + pairs
            base["intraday"] = True
            base["note"] = f"Session of {day.isoformat()}" + (
                "" if previous is None else f", previous close {_two(previous)}"
            )
    else:
        ctx = context(env, None)
        start, end = _price_window(env, ctx, period)
        window = list(
            env.db.scalars(
                select(PriceBar)
                .where(PriceBar.listing_id == listing.id, PriceBar.date <= end)
                .order_by(PriceBar.date)
            )
        )
        before = [b for b in window if b.date <= start]
        points = [(b.date.isoformat(), b.close) for b in window if b.date > start]
        if quote is not None:
            points.append(
                (exchanges.local_time(listing.exchange_mic, quote[1]).date().isoformat(), value)
            )
        reference = before[-1].close if before else (points[0][1] if points else None)
    if reference:
        base["change_ratio"] = str((value / reference - 1).quantize(Decimal("0.000001")))
    if cfg.sparkline and len(points) >= 2:
        base["sparkline"] = [{"date": d, "value": str(v)} for d, v in thin(points, SPARK_POINTS)]
        if base.get("intraday") and reference is not None:
            base["baseline"] = str(reference)
    return base


def _two(value: Decimal) -> str:
    return display_two(value)


def kpi(env: Env, cfg: Any) -> dict[str, Any]:
    metric: str = cfg.metric
    kind = _KINDS[metric]
    base: dict[str, Any] = {"metric": metric, "kind": kind, "value": None, "sparkline": []}
    if metric == "latest_price":
        return _latest_price(env, cfg, base)
    extras = svc.benchmark_ids(env.db, 1) if metric == "beta" else []
    ctx = context_for(env, cfg, extras)
    if ctx.empty:
        return {**base, **_empty("Add a transaction to see this figure.")}
    period = period_of(cfg, env)
    start, end = window_of(ctx, period, env)
    base["start"], base["end"] = start.isoformat(), end.isoformat()
    base["as_of"] = ctx.days[-1].isoformat()

    points = series_for(env, ctx, cfg, start, end)
    result = svc.returns_for(points)
    if cfg.sparkline and points and metric in _TRENDS:
        base["sparkline"] = [
            {"date": p.day.isoformat(), "value": str(p.value)} for p in thin(points, SPARK_POINTS)
        ]

    if metric == "value":
        base["value"] = s(points[-1].value) if points else None
        if result is not None:
            base.update(
                change_eur=s(result.pnl),
                change_ratio=s(result.figures.twr if result.figures else None),
            )
    elif metric == "day_change":
        # the last price day against the one before it, not "yesterday": on a weekend or before
        # the close the calendar yesterday has the same price as today, which showed 0
        priced = [d for d in ctx.trading_days if d <= env.today]
        latest = max(priced) if priced else env.today
        day = series_for(env, ctx, cfg, min(latest, env.today) - timedelta(days=1), env.today)
        one = svc.returns_for(day)
        if one is not None:
            base.update(value=s(one.pnl), change_ratio=s(one.figures.twr if one.figures else None))
    elif metric == "total_return":
        everything = series_for(env, ctx, cfg, ctx.days[0], env.today)
        total = svc.returns_for(everything)
        if total is not None:
            put_in = total.net_flows
            base.update(
                value=s(total.pnl), change_ratio=s(None if put_in <= 0 else total.pnl / put_in)
            )
    elif metric in ("period_return", "twr", "xirr"):
        if result is None:
            return {**base, **_empty("Nothing happened in this period yet.")}
        figures = result.figures
        if metric == "period_return":
            base.update(value=s(result.pnl), change_ratio=s(figures.twr if figures else None))
        else:
            base["value"] = s(getattr(figures, metric) if figures else None)
            base["change_eur"] = s(result.pnl)
            base["breakdown"] = _breakdown(metric, points)
    elif metric == "cash":
        if not ctx.tracks_cash:
            return {**base, **_empty("Turn on cash tracking for an account to see its cash.")}
        base["value"] = s(ctx.points[-1].cash_eur)
    elif metric in ("unrealized", "realized"):
        # open positions at the latest prices (unrealized) and what sales and closed positions
        # have already locked in (realized), for the positions this widget looks at
        rows, _ = load_positions(
            env.db,
            account_id=account_of(cfg, env),
            group_by_isin=True,
            include_closed=True,
            today=env.today,
        )
        only = only_of(cfg, env)
        if only is not None:
            rows = [r for r in rows if r.instrument.id in set(only)]
        if cfg.scope.kind == "instrument":
            rows = [r for r in rows if r.instrument.id == cfg.scope.id]
        elif cfg.scope.kind == "sleeve" and cfg.scope.id is not None:
            ids = set(svc.instruments_in_sleeve(env.db, cfg.scope.id))
            rows = [r for r in rows if r.instrument.id in ids]
        if metric == "realized":
            base["value"] = s(sum((r.state.realized_pnl_eur for r in rows), ZERO))
        else:
            valued = [r for r in rows if r.metrics is not None and r.state.quantity != 0]
            gain = sum((r.metrics.unrealized_pnl_eur for r in valued), ZERO)  # type: ignore[union-attr]
            cost = sum((r.state.cost_basis_eur for r in valued), ZERO)
            base.update(value=s(gain), change_ratio=s(None if cost == 0 else gain / cost))
            skipped = sum(1 for r in rows if r.metrics is None and r.state.quantity != 0)
            if skipped:
                base["note"] = f"{skipped} holding(s) without a price are left out."
    elif metric == "net_contributions":
        base["value"] = s(ctx.points[-1].net_contributions_eur)
    elif metric == "income":
        base["value"] = s(result.income if result else ZERO)
    elif metric == "largest_drift":
        allocation, _ = svc.allocation_at(env.db, ctx, env.today, "sleeve")
        drifted = [x for x in allocation.slices if x.drift is not None]
        if not drifted:
            return {
                **base,
                **_empty("Set targets on your sleeves (Settings, Sleeves) to see drift."),
            }
        worst = max(drifted, key=lambda x: abs(x.drift.pp))  # type: ignore[union-attr]
        base.update(value=s(worst.drift.pp), label=worst.key)  # type: ignore[union-attr]
    else:  # volatility, max_drawdown, current_drawdown, sharpe, beta
        year_start = env.today - timedelta(days=365)
        risk = svc.risk_for(env.db, ctx, year_start, env.today, extras[0] if extras else None)
        if risk is None:
            return {**base, **_empty("There is not enough history for this figure yet.")}
        measured = risk.figures
        value = {
            "volatility": measured.volatility,
            "max_drawdown": measured.max_drawdown,
            "current_drawdown": measured.current_drawdown,
            "sharpe": measured.sharpe,
            "beta": measured.beta,
        }[metric]
        base["value"] = s(value)
        if value is None and metric == "beta":
            base["note"] = "Flag a benchmark (Holdings, Instruments) to see beta."
    return base


# --- charts of the whole history ----------------------------------------------------------------


def value_history(env: Env, cfg: Any) -> dict[str, Any]:
    ctx = context_for(env, cfg)
    if ctx.empty:
        return _empty("Add a transaction to see how your value develops.")
    period = period_of(cfg, env, "MAX")
    start, end = window_of(ctx, period, env)
    # Days on which a holding had no price (its price history starts later than the first
    # transaction) leave that holding out of the value, so the line would sit far below what was
    # paid in. The line starts on the first day after the last such day, so every point is a
    # full valuation. If the newest day is itself short of a price, nothing is cut and the days
    # without a price are counted, so the widget can say so.
    if cfg.scope.kind in ("portfolio", "account"):
        rows = svc.history(ctx, start + timedelta(days=1), end)
        last_short = max((n for n, r in enumerate(rows) if r.unvalued), default=None)
        cut = 0 if last_short is None or last_short == len(rows) - 1 else last_short + 1
        skipped = rows[cut].day if cut else None  # where the line starts instead
        rows = rows[cut:]
        gaps = sum(1 for r in rows if r.unvalued)
        points = [
            {
                "date": r.day.isoformat(),
                "value": str(r.value),
                "net_contributions": str(r.net_contributions),
            }
            for r in rows
        ]
    else:
        series = series_for(env, ctx, cfg, start, end)
        ids = (
            svc.instruments_in_sleeve(env.db, cfg.scope.id)
            if cfg.scope.kind == "sleeve" and cfg.scope.id is not None
            else [cfg.scope.id]
        )
        held = [i for i in ids if i in ctx.instruments]
        offset = ctx.index(start)
        short = [
            any(ctx.instruments[i][offset + k].value is None for i in held)
            for k in range(len(series))
        ]
        last_short = max((k for k in range(1, len(series)) if short[k]), default=None)
        begin = 1 if last_short is None or last_short == len(series) - 1 else last_short + 1
        skipped = series[begin].day if begin > 1 else None
        gaps = sum(1 for k in range(begin, len(series)) if short[k])
        put_in = sum((p.flow for p in series[1:begin]), ZERO)
        points = []
        for k in range(begin, len(series)):
            put_in += series[k].flow
            points.append(
                {
                    "date": series[k].day.isoformat(),
                    "value": str(series[k].value),
                    "net_contributions": str(put_in),
                }
            )
    if not points:
        return _empty("There is no history to show for this period yet.")
    return {
        "points": thin(points, CHART_POINTS),
        "log_scale": cfg.log_scale,
        "period": period,
        "start": points[0]["date"],
        "end": points[-1]["date"],
        "unpriced_before": None if skipped is None else skipped.isoformat(),
        "unpriced_days": gaps,
    }


def drawdown_chart(env: Env, cfg: Any) -> dict[str, Any]:
    ctx = context_for(env, cfg)
    if ctx.empty:
        return _empty("Add a transaction to see drawdowns.")
    start, end = window_of(ctx, period_of(cfg, env, "MAX"), env)
    index = twr_index(series_for(env, ctx, cfg, start, end))[1:]
    if not index:
        return _empty("There is not enough history for this chart yet.")
    under = drawdown(index)
    return {
        "points": thin(
            [{"date": d.isoformat(), "value": str(v)} for d, v in under.series], CHART_POINTS
        ),
        "max_drawdown": str(under.maximum),
        "current_drawdown": str(under.current),
        "max_start": None if under.maximum_start is None else under.maximum_start.isoformat(),
        "max_end": None if under.maximum_end is None else under.maximum_end.isoformat(),
    }


def monthly(env: Env, cfg: Any) -> dict[str, Any]:
    ctx = context_for(env, cfg)
    if ctx.empty:
        return _empty("Add a transaction to see monthly returns.")
    series = series_for(env, ctx, cfg, ctx.days[0], env.today)
    index = twr_index(series)
    by_month = monthly_returns(index)
    years: dict[int, dict[int, str]] = defaultdict(dict)
    for (year, month), value in by_month.items():
        years[year][month] = str(value)
    totals: dict[int, str] = {}
    for year in years:
        grown = Decimal(1)
        for month in range(1, 13):
            if str(month) in {str(k) for k in years[year]} or month in years[year]:
                grown *= 1 + Decimal(years[year][month])
        totals[year] = str(grown - 1)
    return {
        "years": [
            {
                "year": y,
                "months": {str(m): v for m, v in sorted(years[y].items())},
                "total": totals[y],
            }
            for y in sorted(years, reverse=True)
        ]
    }


# --- composition --------------------------------------------------------------------------------


def _exposure(e: Exposure) -> dict[str, Any]:
    return {
        "key": e.label,
        "value_eur": str(e.value_eur),
        "weight": str(e.weight),
        "other": e.other,
        "parts": [
            {
                "source": p.source,
                "instrument_id": p.instrument_id,
                "kind": p.kind,
                "value_eur": str(p.value_eur),
                "weight_pct": s(p.weight_pct),
            }
            for p in e.parts
        ],
    }


def allocation(env: Env, cfg: Any) -> dict[str, Any]:
    if cfg.look_through:
        if cfg.group_by not in DIMENSIONS:
            raise WidgetDataError(
                "Look-through groups by company, sector, country or currency. Change the grouping."
            )
        ctx = context_for(env, cfg)
        opened = svc.look_through_at(env.db, ctx, env.today, cfg.group_by)
        if not opened.exposures:
            return _empty("Add a holding to see how your portfolio is divided.")
        return {
            "group_by": cfg.group_by,
            "chart": cfg.chart,
            "show_target": False,
            "look_through": True,
            "total_eur": str(opened.total_eur),
            "unvalued": opened.unvalued,
            "unopened": opened.unopened,
            "slices": [
                {**_exposure(e), "target": None, "drift_pp": None, "outside_band": None}
                for e in opened.exposures
            ],
        }
    if cfg.group_by in ("company", "country"):
        raise WidgetDataError(f"Grouping by {cfg.group_by} needs look-through switched on.")
    ctx = context_for(env, cfg)
    result, unvalued = svc.allocation_at(env.db, ctx, env.today, cfg.group_by)
    if result.total_eur == 0 and not result.slices:
        reason = (
            "None of your holdings has a price yet. Enter one under Holdings, Instruments, "
            "or wait for the nightly fetch."
            if unvalued
            else "Add a holding to see how your portfolio is divided."
        )
        return {**_empty(reason), "unvalued": unvalued}
    return {
        "group_by": cfg.group_by,
        "chart": cfg.chart,
        "show_target": cfg.show_target,
        "total_eur": str(result.total_eur),
        "unvalued": unvalued,
        "slices": [
            {
                "key": x.key,
                "value_eur": str(x.value_eur),
                "weight": str(x.weight),
                "target": s(None if x.drift is None else x.drift.target),
                "drift_pp": s(None if x.drift is None else x.drift.pp),
                "outside_band": None if x.drift is None else x.drift.outside_band,
            }
            for x in result.slices
        ],
    }


def look_through(env: Env, cfg: Any) -> dict[str, Any]:
    """The largest underlying exposures across direct holdings and ETFs (FR-PF-05)."""
    ctx = context_for(env, cfg)
    opened = svc.look_through_at(env.db, ctx, env.today, cfg.dimension)
    if not opened.exposures:
        return _empty("Add a holding to see what you hold underneath.")
    if not opened.opened and opened.unopened:
        return _empty(
            "None of your ETFs has its holdings yet. Open an ETF under Holdings and upload its "
            "holdings file."
        )
    shown = opened.exposures[: cfg.top_n]
    return {
        "dimension": cfg.dimension,
        "total_eur": str(opened.total_eur),
        "slices": [_exposure(e) for e in shown],
        "rest_weight": str(sum((e.weight for e in opened.exposures[cfg.top_n :]), ZERO)),
        "opened": [{"name": n, "holdings_as_of": d.isoformat()} for n, d in opened.opened],
        "unopened": opened.unopened,
        "unvalued": opened.unvalued,
    }


def drift_bars(env: Env, cfg: Any) -> dict[str, Any]:
    ctx = context_for(env, cfg)
    result, _ = svc.allocation_at(env.db, ctx, env.today, "sleeve")
    targets = svc.sleeve_targets(env.db)
    bars = [
        {
            "key": x.key,
            "weight": str(x.weight),
            "target": str(x.drift.target),
            "drift_pp": str(x.drift.pp),
            "band": s(targets.get(x.key, (None, None))[1]),
            "outside_band": x.drift.outside_band,
        }
        for x in result.slices
        if x.drift is not None
    ]
    if not bars:
        return _empty("Set targets on your sleeves (Settings, Sleeves) to see drift.")
    return {"bars": bars}


def _target_weights(db: Session, rows: list[Any], meta: dict[int, Any]) -> dict[int, Decimal]:
    """The target share of the portfolio of each holding in a sleeve that has a target: the
    sleeve's target split between its holdings in proportion to what they are worth now. The
    sleeves' targets come from the active strategy (or Settings, Sleeves), so a holding is
    "over" its target exactly when its sleeve is."""
    targets = svc.sleeve_targets(db)
    in_sleeve: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for r in rows:
        name = meta[r.instrument.id].sleeve if r.instrument.id in meta else None
        if name in targets and r.weight is not None:
            in_sleeve[name] += r.weight
    out: dict[int, Decimal] = {}
    for r in rows:
        name = meta[r.instrument.id].sleeve if r.instrument.id in meta else None
        if name in targets and r.weight is not None and in_sleeve[name] != 0:
            out[r.instrument.id] = targets[name][0] * r.weight / in_sleeve[name]
    return out


def holdings_table(env: Env, cfg: Any) -> dict[str, Any]:
    # one line per instrument: the accounts it is split over are an administrative detail here
    rows, totals = load_positions(
        env.db, account_id=account_of(cfg, env), group_by_isin=True, today=env.today
    )
    only = only_of(cfg, env)
    if only is not None:
        rows = [r for r in rows if r.instrument.id in set(only)]
        totals = totals_for(rows)
        if not rows:
            return _empty("Nothing you hold matches the type or holding filter.")
    if not rows:
        return _empty("Add your first instrument and a transaction to see positions here.")
    meta = svc.load_meta(env.db, {r.instrument.id for r in rows})
    targets = _target_weights(env.db, rows, meta)
    out = []
    for r in rows:
        m = r.metrics
        target = targets.get(r.instrument.id)
        # "last close" is the close before the latest price: while a newer quote exists that is
        # the newest close, and once the day's own close is the latest price it is the day before
        price = r.price
        quoted = price is not None and price.delayed_price is not None
        before = None if price is None else (price.close if quoted else price.previous_close)
        before_date = None if price is None else (price.date if quoted else price.previous_date)
        latest = None if price is None else (price.delayed_price if quoted else price.close)
        out.append(
            {
                "instrument_id": r.instrument.id,
                "name": r.instrument.name,
                "account": ", ".join(a.name for a in r.accounts),
                "asset_class": r.instrument.asset_class,
                "sleeve": meta[r.instrument.id].sleeve if r.instrument.id in meta else None,
                "quantity": str(r.state.quantity),
                "avg_cost_eur": s(r.state.avg_cost_eur),
                "cost_basis_eur": str(r.state.cost_basis_eur),
                "close": s(before),
                "close_date": None if before_date is None else before_date.isoformat(),
                "latest": s(latest),
                "latest_at": (
                    r.price.delayed_at.isoformat() if r.price and r.price.delayed_at else None
                ),
                "target_weight": s(target),
                "weight_diff": s(None if target is None or r.weight is None else r.weight - target),
                "stale": bool(r.price and r.price.stale),
                "value": s(getattr(m, "market_value_eur", None)),
                "weight": s(r.weight),
                "unrealized": s(getattr(m, "unrealized_pnl_eur", None)),
                "unrealized_ratio": s(getattr(m, "unrealized_pct", None)),
                "day": s(getattr(m, "day_change_eur", None)),
                "day_ratio": s(getattr(m, "day_change_pct", None)),
                "total_return": s(getattr(m, "total_return_eur", None)),
                "income": str(r.state.income_eur),
            }
        )
    return {
        "columns": cfg.columns,
        "group_by": cfg.group_by,
        "sort_by": cfg.sort_by,
        "sort_dir": cfg.sort_dir,
        "rows": out,
        "totals": {
            "value": str(totals.market_value_eur),
            "unrealized": str(totals.unrealized_pnl_eur),
            "unrealized_ratio": s(totals.unrealized_pct),
            "day": s(totals.day_change_eur),
            "income": str(totals.income_eur),
        },
    }


def heatmap(env: Env, cfg: Any) -> dict[str, Any]:
    ctx = context_for(env, cfg)
    if ctx.empty:
        return _empty("Add a holding to see how each position performed.")
    start, end = window_of(ctx, period_of(cfg, env, "1M"), env)
    meta = svc.load_meta(env.db, ctx.instruments)
    cells = []
    for instrument_id in ctx.instruments:
        result = svc.returns_for(svc.instrument_series(ctx, [instrument_id], start, end))
        if result is None or (result.value_end == 0 and result.pnl == 0):
            continue
        cells.append(
            {
                "instrument_id": instrument_id,
                "name": meta[instrument_id].name if instrument_id in meta else str(instrument_id),
                "twr": s(result.figures.twr if result.figures else None),
                "pnl_eur": str(result.pnl),
                "value_eur": str(result.value_end),
            }
        )
    if not cells:
        return _empty("No position was held in this period.")
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "cells": sorted(cells, key=lambda c: -Decimal(c["value_eur"])),
    }


def correlation(env: Env, cfg: Any) -> dict[str, Any]:
    ctx = context_for(env, cfg)
    held = svc.held_instruments(ctx, env.today)
    if len(held) < 2:
        return _empty("Hold at least two priced instruments to see how they move together.")
    meta = svc.load_meta(env.db, held)
    ids = [i for i in held if i in meta]
    span = 90 if cfg.window == "90D" else 365
    matrix = svc.correlations(ctx, env.today - timedelta(days=span), env.today, ids)
    return {
        "window": cfg.window,
        "instruments": [{"id": i, "name": meta[i].name} for i in ids],
        "values": [[s(matrix[a].get(b)) for b in ids] for a in ids],
    }


def return_bridge(env: Env, cfg: Any) -> dict[str, Any]:
    ctx = context_for(env, cfg)
    if ctx.empty:
        return _empty("Add a transaction to see where your result comes from.")
    start, end = window_of(ctx, period_of(cfg, env), env)
    first, last = ctx.index(start), ctx.index(end)
    meta = svc.load_meta(env.db, ctx.instruments)
    positions = []
    for instrument_id, states in ctx.instruments.items():
        a, b = states[first], states[last]
        v0, v1 = a.value or ZERO, b.value or ZERO
        flows = b.net_invested_eur - a.net_invested_eur
        if v0 == 0 and v1 == 0 and flows == 0:
            continue
        name = meta[instrument_id].name if instrument_id in meta else str(instrument_id)
        positions.append((name, v0, v1, flows))
    start_value = sum((p[1] for p in positions), ZERO)
    steps = bridge(start_value, positions)
    return {
        "start": ctx.days[first].isoformat(),
        "end": ctx.days[last].isoformat(),
        "steps": [
            {"label": x.label, "amount_eur": str(x.amount_eur), "kind": x.kind} for x in steps
        ],
    }


def attribution(env: Env, cfg: Any) -> dict[str, Any]:
    """What each position contributed to the period's result, in euro and in points of the return;
    the euro figures add up to the portfolio's result (FR-PF-07)."""
    ctx = context_for(env, cfg)
    if ctx.empty:
        return _empty("Add a transaction to see what each position contributed.")
    start, end = window_of(ctx, period_of(cfg, env, "1Y"), env)
    result = svc.attribution_for(ctx, start, end)
    if result is None:
        return _empty("Nothing happened in this period to attribute.")
    meta = svc.load_meta(env.db, ctx.instruments)
    rows: list[dict[str, Any]] = []
    for c in sorted(result.attribution.contributions, key=lambda x: -abs(x.pnl_eur)):
        if c.key == svc.OTHER:
            name = "Other (costs and interest)"
        else:
            found = meta.get(int(c.key))
            name = found.name if found else str(c.key)
        rows.append(
            {
                "key": str(c.key),
                "name": name,
                "pnl_eur": str(c.pnl_eur),
                "points": s(c.points),
            }
        )
    return {
        "start": result.start.isoformat(),
        "end": result.end.isoformat(),
        "portfolio_pnl_eur": str(result.portfolio_pnl_eur),
        "total_return": s(result.attribution.total_return),
        "rows": rows,
    }


def income(env: Env, cfg: Any) -> dict[str, Any]:
    account = account_of(cfg, env)
    ctx = context_for(env, cfg)
    if ctx.empty:
        return _empty("Dividends and interest will show here once you record them.")
    start, end = window_of(ctx, period_of(cfg, env, "1Y"), env)
    query = select(LedgerTransaction).where(
        LedgerTransaction.deleted_at.is_(None),
        LedgerTransaction.status == "posted",
        LedgerTransaction.type.in_(("dividend", "interest")),
        LedgerTransaction.trade_date > start,
        LedgerTransaction.trade_date <= end,
    )
    if account is not None:
        query = query.where(LedgerTransaction.account_id == account)
    months: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"dividends": ZERO, "interest": ZERO}
    )
    total = ZERO
    for tx in env.db.scalars(query):
        amount = tx.net_amount_eur or ZERO
        months[tx.trade_date.strftime("%Y-%m")][
            "dividends" if tx.type == "dividend" else "interest"
        ] += amount
        total += amount
    if not months:
        return _empty("No dividends or interest were received in this period.")
    return {
        "months": [
            {"month": m, "dividends": str(v["dividends"]), "interest": str(v["interest"])}
            for m, v in sorted(months.items())
        ],
        "total_eur": str(total),
    }


# --- price and comparison charts ----------------------------------------------------------------


def _moving_average(closes: list[tuple[date, Decimal]], n: int) -> list[dict[str, str]]:
    out = []
    for i in range(n - 1, len(closes)):
        window = closes[i - n + 1 : i + 1]
        out.append(
            {"date": closes[i][0].isoformat(), "value": str(sum((c for _, c in window), ZERO) / n)}
        )
    return out


PERCENT_PLACES = Decimal("0.0001")


def _percent(value: Decimal, base: Decimal) -> str:
    return str(((value / base - 1) * 100).quantize(PERCENT_PLACES))


def _step_changes(
    points: Sequence[tuple[str, Decimal]], base: Decimal | None
) -> list[dict[str, str]]:
    """The percent change of each point against the one before it (the first against `base`)."""
    out: list[dict[str, str]] = []
    before = base
    for day, close in points:
        if before is not None and before != 0:
            out.append({"date": day, "value": _percent(close, before)})
        before = close
    return out


def _since_start(
    points: Sequence[tuple[str, Decimal]], base: Decimal | None
) -> list[dict[str, str]]:
    """The percent change of each point against `base` (the first point when there is none)."""
    if not points:
        return []
    start = base if base else points[0][1]
    if start == 0:
        return []
    return [{"date": day, "value": _percent(close, start)} for day, close in points]


def _shows_price(cfg: Any) -> bool:
    """The price itself is drawn unless only a change view was asked for."""
    return "price" in cfg.overlays or not ({"changes", "since_start"} & set(cfg.overlays))


def _change_views(
    cfg: Any, points: Sequence[tuple[str, Decimal]], base: Decimal | None
) -> dict[str, Any]:
    """The chosen change views of a price chart, with whether the price is drawn."""
    views: dict[str, Any] = {}
    if "changes" in cfg.overlays:
        views["changes"] = _step_changes(points, base)
    if "since_start" in cfg.overlays:
        views["since_start"] = _since_start(points, base)
    views["show_price"] = _shows_price(cfg)
    return views


def _primary_listing(env: Env, instrument_id: int) -> Listing | None:
    return env.db.scalars(
        select(Listing)
        .where(Listing.instrument_id == instrument_id)
        .order_by(Listing.pricing_primary.desc(), Listing.id)
        .limit(1)
    ).first()


def _session(
    env: Env, listing: Listing
) -> tuple[date, list[tuple[str, Decimal]], Decimal | None] | None:
    """The latest session with refresh prices on record for a listing: its exchange-local date,
    its quotes in order as (exchange-local time, price), and the close before that date. None
    when no quote is stored."""
    latest = env.db.scalars(
        select(Quote).where(Quote.listing_id == listing.id).order_by(Quote.ts.desc()).limit(1)
    ).first()
    if latest is None:
        return None
    mic = listing.exchange_mic
    day = exchanges.local_date(mic, latest.ts)
    quotes = [
        q
        for q in env.db.scalars(
            select(Quote)
            .where(Quote.listing_id == listing.id, Quote.ts >= latest.ts - timedelta(hours=36))
            .order_by(Quote.ts)
        )
        if exchanges.local_date(mic, q.ts) == day
    ]
    before = env.db.scalars(
        select(PriceBar)
        .where(PriceBar.listing_id == listing.id, PriceBar.date < day)
        .order_by(PriceBar.date.desc())
        .limit(1)
    ).first()
    pairs = [(exchanges.local_time(mic, q.ts).isoformat(), q.price) for q in quotes]
    return day, pairs, None if before is None else before.close


NO_REFRESH_PRICES = (
    "No refresh prices are stored for this instrument yet. They are fetched every 15 "
    "minutes while its exchange is open, and only for what you hold or watch."
)


def _price_window(env: Env, ctx: svc.AnalyticsContext, period: str) -> tuple[date, date]:
    """The start and end of a period for a price (a year back when nothing is held yet)."""
    try:
        if ctx.empty:
            return env.today - timedelta(days=365), env.today
        return svc.resolve(ctx, period, env.today, env.filters.start, env.filters.end)
    except ValueError as exc:
        raise WidgetDataError(str(exc)) from exc


def _intraday(env: Env, cfg: Any, instrument: Instrument, listing: Listing) -> dict[str, Any]:
    """One day of a price chart: the refresh prices (quotes) of the latest session on record,
    in exchange-local time, against the close before it."""
    session = _session(env, listing)
    if session is None:
        return _empty(NO_REFRESH_PRICES)
    day, pairs, previous = session
    return {
        "instrument_id": instrument.id,
        "name": instrument.name,
        "currency": listing.currency,
        "chart": "line",  # the refresh prices have no open, high or low
        "intraday": True,
        "session_date": day.isoformat(),
        "previous_close": s(previous),
        "points": [
            {"date": d, "open": None, "high": None, "low": None, "close": str(c), "volume": None}
            for d, c in pairs
        ],
        "trades": [],
        **_change_views(cfg, pairs, previous),
    }


def price_chart(env: Env, cfg: Any) -> dict[str, Any]:
    instrument_id = cfg.instrument_id or (cfg.scope.id if cfg.scope.kind == "instrument" else None)
    if instrument_id is None:
        return _empty("Choose an instrument for this chart.")
    instrument = env.db.get(Instrument, instrument_id)
    if instrument is None or instrument.deleted_at is not None:
        raise WidgetDataError("That instrument no longer exists.")
    listing = _primary_listing(env, instrument_id)
    if listing is None:
        return _empty("This instrument has no listing to chart.")
    period = period_of(cfg, env, "1Y")
    if period == "1D":
        return _intraday(env, cfg, instrument, listing)
    ctx = context(env, None)
    first_day = ctx.first_transaction_day
    start, end = _price_window(env, ctx, period)
    warm = start - timedelta(days=300)  # the 200-day average needs history before the window
    bars = list(
        env.db.scalars(
            select(PriceBar)
            .where(PriceBar.listing_id == listing.id, PriceBar.date >= warm, PriceBar.date <= end)
            .order_by(PriceBar.date)
        )
    )
    if not bars:
        return _empty("No prices are stored for this instrument yet.")
    closes = [(b.date, b.close) for b in bars]
    shown = [b for b in bars if b.date > start]
    trades = []
    if "trades" in cfg.overlays and _shows_price(cfg):
        for tx in env.db.scalars(
            select(LedgerTransaction)
            .where(
                LedgerTransaction.instrument_id == instrument_id,
                LedgerTransaction.type.in_(("buy", "sell")),
                LedgerTransaction.deleted_at.is_(None),
                LedgerTransaction.status == "posted",
                LedgerTransaction.trade_date > start,
                LedgerTransaction.trade_date <= end,
            )
            .order_by(LedgerTransaction.trade_date)
        ):
            trades.append(
                {
                    "date": tx.trade_date.isoformat(),
                    "type": tx.type,
                    "quantity": str(tx.quantity),
                    "price": str(tx.price),
                }
            )
    points = thin(shown, CHART_POINTS)  # the changes are between the points the chart shows
    out: dict[str, Any] = {
        "instrument_id": instrument_id,
        "name": instrument.name,
        "currency": listing.currency,
        "chart": cfg.chart,
        "first_transaction": None if first_day is None else first_day.isoformat(),
        "points": [
            {
                "date": b.date.isoformat(),
                "open": s(b.open),
                "high": s(b.high),
                "low": s(b.low),
                "close": str(b.close),
                "volume": s(b.volume),
            }
            for b in points
        ],
        "trades": trades,
        **_change_views(
            cfg,
            [(b.date.isoformat(), b.close) for b in points],
            next((c for d, c in reversed(closes) if d <= start), None),
        ),
    }  # fmt: skip
    if out["show_price"]:
        for key, n in (("ma50", 50), ("ma200", 200)):
            if key in cfg.overlays:
                out[key] = [p for p in _moving_average(closes, n) if p["date"] > start.isoformat()]
    return out


def performance(env: Env, cfg: Any) -> dict[str, Any]:
    refs = list(cfg.series)
    benchmarks = svc.benchmark_ids(env.db)
    if not refs:
        refs = [{"kind": "portfolio", "id": None}] + [
            {"kind": "benchmark", "id": i} for i in benchmarks
        ]
    else:
        refs = [r.model_dump() for r in refs]
    price_ids = [
        r["id"] for r in refs if r["kind"] in ("benchmark", "instrument") and r["id"] is not None
    ]
    ctx = context_for(env, cfg, price_ids)
    if ctx.empty:
        return _empty("Add a transaction to compare your portfolio with benchmarks.")
    start, end = window_of(ctx, period_of(cfg, env), env)
    meta = svc.load_meta(env.db, price_ids)
    sleeves = {s_.id: s_.name for s_ in _sleeves(env.db)}
    out: list[dict[str, Any]] = []
    first, last = ctx.index(start), ctx.index(end)
    for ref in refs:
        kind, ident = ref["kind"], ref["id"]
        if kind == "portfolio":
            points = svc.window(ctx, svc.portfolio_series(ctx), start, end)
            rebased = [(p, v * 100) for p, v in twr_index(points)]
            out.append({"key": "portfolio", "label": "Portfolio", "points": rebased})
        elif kind == "sleeve" and ident is not None:
            ids = svc.instruments_in_sleeve(env.db, ident)
            points = svc.instrument_series(ctx, ids, start, end)
            out.append({"key": f"sleeve:{ident}", "label": sleeves.get(ident, str(ident)),
                        "points": [(p, v * 100) for p, v in twr_index(points)]})  # fmt: skip
        elif ident is not None and ident in ctx.prices:
            prices = [
                (ctx.days[n], p)
                for n, p in enumerate(ctx.prices[ident][first : last + 1], start=first)
                if p is not None
            ]
            label = meta[ident].name if ident in meta else str(ident)
            out.append(
                {
                    "key": f"{kind}:{ident}",
                    "label": label,
                    "points": rebase(prices, ctx.days[first]),
                }
            )
    return {
        "start": ctx.days[first].isoformat(),
        "end": ctx.days[last].isoformat(),
        "suggest_benchmark": not benchmarks,  # none chosen yet (owner decision Q9)
        "series": [
            {
                "key": x["key"],
                "label": x["label"],
                "points": thin(
                    [{"date": d.isoformat(), "value": str(v)} for d, v in x["points"]],
                    CHART_POINTS,
                ),
            }
            for x in out
        ],
    }  # fmt: skip


def _sleeves(db: Session) -> list[Any]:
    from folio.db.models_analytics import Sleeve

    return list(db.scalars(select(Sleeve).where(Sleeve.deleted_at.is_(None))))


# --- macro ---------------------------------------------------------------------------------------

_PERIOD_DAYS = {"1D": 30, "1W": 30, "1M": 31, "3M": 92, "1Y": 366, "3Y": 3 * 366, "5Y": 5 * 366}


def _macro_window(env: Env, cfg: Any) -> tuple[date, date]:
    period = period_of(cfg, env, "1Y")
    if period == "CUSTOM" and env.filters.start and env.filters.end:
        return env.filters.start, env.filters.end
    if period == "YTD":
        return date(env.today.year, 1, 1), env.today
    if period == "MAX":
        return env.today - timedelta(days=5 * 366), env.today
    return env.today - timedelta(days=_PERIOD_DAYS.get(period, 366)), env.today


SEVERITY_ORDER = ("info", "low", "medium", "high", "critical")
NEWS_DAYS = 7
SIGNAL_DAYS = 14
FEED_ROWS = 8
PROJECTION_PATHS = 1000  # enough for a smooth band on a dashboard


def _end_of(day: date) -> datetime:
    return datetime.combine(day, time.max, UTC)


def news_feed(env: Env, cfg: Any) -> dict[str, Any]:
    """The latest stories linked to what you hold, with their assessment (FR-NW-07)."""
    floor = datetime.combine(env.today - timedelta(days=NEWS_DAYS), time.min, UTC)
    query = select(NewsCluster).where(
        NewsCluster.relevance > 0,
        NewsCluster.last_seen >= floor,
        NewsCluster.last_seen <= _end_of(env.today),
    )
    if cfg.min_impact:
        query = query.where(NewsCluster.max_impact >= cfg.min_impact)
    names = {i.id: i.name for i in env.db.scalars(select(Instrument))}
    stories = []
    for c in env.db.scalars(query.order_by(NewsCluster.last_seen.desc()).limit(FEED_ROWS)):
        latest = env.db.scalars(
            select(NewsAssessment)
            .where(NewsAssessment.cluster_id == c.id)
            .order_by(NewsAssessment.id.desc())
        ).first()
        links = env.db.scalars(
            select(NewsLink)
            .where(NewsLink.cluster_id == c.id)
            .order_by(NewsLink.relevance.desc())
            .limit(3)
        )
        stories.append(
            {
                "id": c.id,
                "title": c.title,
                "last_seen": c.last_seen.isoformat(),
                "impact": None if latest is None else latest.impact_score,
                "direction": None if latest is None else latest.direction,
                "links": [names.get(k.instrument_id or 0, k.sleeve or "?") for k in links],
            }
        )
    if not stories:
        return _empty(
            "No stories linked to your holdings yet. Check your sources under Settings, News."
        )
    return {"stories": stories}


def signals(env: Env, cfg: Any) -> dict[str, Any]:
    """What is waiting for you: open recommendations, then the strategy's recent signals at or
    above the chosen severity (FR-ST-04, FR-AG-05)."""
    now = _end_of(env.today)
    minimum = 0 if cfg.severity == "all" else SEVERITY_ORDER.index(cfg.severity)
    items: list[dict[str, Any]] = []
    for r in env.db.scalars(
        select(Recommendation)
        .where(Recommendation.status.in_(("new", "seen")), Recommendation.expires_at > now)
        .order_by(Recommendation.id.desc())
        .limit(FEED_ROWS)
    ):
        if SEVERITY_ORDER.index(r.severity) < minimum:
            continue
        items.append(
            {
                "kind": "recommendation",
                "id": r.id,
                "title": r.title,
                "severity": r.severity,
                "time": r.created_at.isoformat(),
                "departs": bool(r.departs_from_principles),
            }
        )
    floor = datetime.combine(env.today - timedelta(days=SIGNAL_DAYS), time.min, UTC)
    for sig in env.db.scalars(
        select(Signal)
        .where(Signal.shadow.is_(False), Signal.ts >= floor, Signal.ts <= now)
        .order_by(Signal.ts.desc())
        .limit(30)
    ):
        if SEVERITY_ORDER.index(sig.severity) < minimum:
            continue
        items.append(
            {
                "kind": "signal",
                "id": sig.id,
                "title": str((sig.payload or {}).get("title") or sig.message),
                "severity": sig.severity,
                "time": sig.ts.isoformat(),
                "departs": False,
            }
        )
    if not items:
        return _empty("Nothing is waiting for you.")
    items.sort(key=lambda i: (-SEVERITY_ORDER.index(i["severity"]), i["kind"] != "recommendation"))
    return {"items": items[:FEED_ROWS]}


def macro_overlay(env: Env, cfg: Any) -> dict[str, Any]:
    stored = list(env.db.scalars(select(MacroSeries).order_by(MacroSeries.id)))
    if not stored:
        return _empty(
            "No indicator data yet. The macro job fetches it every morning; FRED series need a "
            "free API key (Settings, Providers)."
        )
    by_code = {m.code: m for m in stored}
    wanted = [c for c in (cfg.series_code, cfg.second_code) if c]
    if not wanted:  # the first two that have data, in the order they were added
        wanted = [m.code for m in stored if m.code != "ECB_DFR"][:2] or [stored[0].code]
    start, end = _macro_window(env, cfg)
    panes = []
    for code in wanted:
        series = by_code.get(code)
        if series is None:
            raise WidgetDataError(f"There is no stored series {code!r}.")
        points = [
            {"date": p.date.isoformat(), "value": str(p.value)}
            for p in env.db.scalars(
                select(MacroPoint)
                .where(MacroPoint.series_id == series.id, MacroPoint.date >= start,
                       MacroPoint.date <= end)
                .order_by(MacroPoint.date)
            )
        ]  # fmt: skip
        panes.append(
            {
                "code": code,
                "name": series.name,
                "unit": series.unit,
                "points": thin(points, CHART_POINTS),
            }  # fmt: skip
        )
    out: dict[str, Any] = {"start": start.isoformat(), "end": end.isoformat(), "panes": panes}
    if cfg.instrument_id is not None:
        ctx = context(env, None, [cfg.instrument_id])
        instrument = env.db.get(Instrument, cfg.instrument_id)
        if instrument is None or ctx.empty or cfg.instrument_id not in ctx.prices:
            raise WidgetDataError("That instrument has no prices to show.")
        first, last = ctx.index(start), ctx.index(end)
        prices = [
            (ctx.days[n], p)
            for n, p in enumerate(ctx.prices[cfg.instrument_id][first : last + 1], start=first)
            if p is not None
        ]
        rebased = rebase(prices, ctx.days[first]) if prices else []
        out["instrument"] = {
            "id": instrument.id,
            "name": instrument.name,
            "points": thin(
                [{"date": d.isoformat(), "value": str(v)} for d, v in rebased], CHART_POINTS
            ),
        }
    return out


# --- notes -------------------------------------------------------------------------------------


def note(env: Env, cfg: Any) -> dict[str, Any]:
    return {"text": cfg.text}


def projection(env: Env, cfg: Any) -> dict[str, Any]:
    """The median and the 10th to 90th percentile band of the portfolio's future value with the
    widget's own assumptions, shown with the assumptions on the chart (FR-PF-12)."""
    ctx = context_for(env, cfg)
    if ctx.empty:
        return _empty("There is nothing to project yet: no transactions.")
    result = svc.project_portfolio(
        env.db,
        ctx,
        env.today,
        years=cfg.years,
        monthly_contribution=cfg.monthly_contribution,
        return_pct=cfg.return_pct,
        volatility_pct=cfg.volatility_pct,
        paths=PROJECTION_PATHS,
        seed=1,
    )
    a = result.projection.assumptions
    step = 1 if cfg.years <= 10 else 3  # fewer points for a long horizon
    months = result.projection.points
    return {
        "assumptions": {
            "start_value_eur": str(a.start_value_eur),
            "monthly_contribution_eur": str(a.monthly_contribution_eur),
            "annual_return_pct": str(a.annual_return_pct),
            "annual_volatility_pct": str(a.annual_volatility_pct),
            "years": a.years,
            "paths": a.paths,
        },
        "points": [
            {
                "date": _months_on(env.today, p.month).isoformat(),
                "invested": str(p.invested_eur),
                "p10": str(p.p10_eur),
                "median": str(p.median_eur),
                "p90": str(p.p90_eur),
            }
            for p in months
            if p.month % step == 0 or p.month == months[-1].month
        ],
    }


def _months_on(day: date, months: int) -> date:
    index = day.year * 12 + (day.month - 1) + months
    year, month0 = divmod(index, 12)
    return date(year, month0 + 1, min(day.day, calendar.monthrange(year, month0 + 1)[1]))


def ask(env: Env, cfg: Any) -> dict[str, Any]:
    """The question box needs only to know whether the agent is on; the questions and answers go
    through the agent endpoints (FR-DB-09)."""
    enabled = agent_settings(env.db).enabled
    return {
        "empty": not enabled,
        "reason": None if enabled else "The AI agent is switched off in Settings, Agent.",
        "show_last": cfg.show_last,
    }


COMPUTE: dict[str, Callable[[Env, Any], dict[str, Any]]] = {
    "kpi": kpi,
    "value_history": value_history,
    "price_chart": price_chart,
    "performance_comparison": performance,
    "allocation": allocation,
    "drift_bars": drift_bars,
    "holdings_table": holdings_table,
    "returns_heatmap": heatmap,
    "monthly_returns": monthly,
    "look_through": look_through,
    "correlation_matrix": correlation,
    "drawdown": drawdown_chart,
    "return_bridge": return_bridge,
    "attribution": attribution,
    "income": income,
    "macro_overlay": macro_overlay,
    "news_feed": news_feed,
    "signals": signals,
    "projection": projection,
    "ask": ask,
    "note": note,
}


def compute(env: Env, kind: str, config: dict[str, Any]) -> dict[str, Any]:
    widget = WIDGET_TYPES.get(kind)
    if widget is None:
        raise WidgetDataError(f"Unknown widget type {kind!r}.")
    return COMPUTE[kind](env, widget.config.model_validate(config))
