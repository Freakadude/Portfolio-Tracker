"""The data behind each widget (FR-DB-03, FR-DB-05). One function per widget type; each takes
the widget's validated options and the dashboard's filters and returns plain JSON (decimals as
strings). They all read the shared analytics context, so a dashboard with many widgets does the
heavy work once."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio import analytics_service as svc
from folio.analytics.returns import DailyPoint, twr_index
from folio.analytics.risk import drawdown
from folio.analytics.series import bridge, monthly_returns, rebase
from folio.dashboards.widgets import WIDGET_TYPES, BaseConfig
from folio.db.models_ledger import Instrument, LedgerTransaction, Listing, PriceBar
from folio.positions import load_positions

ZERO = Decimal(0)
SPARK_POINTS = 60
CHART_POINTS = 800


class WidgetDataError(ValueError):
    """The widget cannot be drawn with these options; the message says what to change."""


@dataclass(frozen=True)
class Filters:
    period: str | None = None
    account: int | None = None


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


def context(env: Env, account: int | None, extras: Sequence[int] = ()) -> svc.AnalyticsContext:
    return svc.get_context(env.db, env.today, account, extras)


def window_of(ctx: svc.AnalyticsContext, period: str, env: Env) -> tuple[date, date]:
    try:
        return svc.resolve(ctx, period, env.today)
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
    "value": "eur", "day_change": "eur", "total_return": "eur", "period_return": "eur",
    "twr": "pct", "xirr": "pct", "cash": "eur", "net_contributions": "eur", "income": "eur",
    "largest_drift": "pct", "volatility": "pct", "max_drawdown": "pct",
    "current_drawdown": "pct", "sharpe": "number", "beta": "number",
}  # fmt: skip


def kpi(env: Env, cfg: Any) -> dict[str, Any]:
    metric: str = cfg.metric
    kind = _KINDS[metric]
    base: dict[str, Any] = {"metric": metric, "kind": kind, "value": None, "sparkline": []}
    account = account_of(cfg, env)
    extras = svc.benchmark_ids(env.db, 1) if metric == "beta" else []
    ctx = context(env, account, extras)
    if ctx.empty:
        return {**base, **_empty("Add a transaction to see this figure.")}
    period = period_of(cfg, env)
    start, end = window_of(ctx, period, env)
    base["start"], base["end"] = start.isoformat(), end.isoformat()
    base["as_of"] = ctx.days[-1].isoformat()

    points = series_for(env, ctx, cfg, start, end)
    result = svc.returns_for(points)
    if cfg.sparkline and points:
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
        day = series_for(env, ctx, cfg, env.today - timedelta(days=1), env.today)
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
    elif metric == "cash":
        if not ctx.tracks_cash:
            return {**base, **_empty("Turn on cash tracking for an account to see its cash.")}
        base["value"] = s(ctx.points[-1].cash_eur)
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
    account = account_of(cfg, env)
    ctx = context(env, account)
    if ctx.empty:
        return _empty("Add a transaction to see how your value develops.")
    start, end = window_of(ctx, period_of(cfg, env, "MAX"), env)
    if cfg.scope.kind in ("portfolio", "account"):
        rows = svc.history(ctx, start + timedelta(days=1), end)
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
        put_in = ZERO
        points = []
        for p in series[1:]:
            put_in += p.flow
            points.append(
                {"date": p.day.isoformat(), "value": str(p.value), "net_contributions": str(put_in)}
            )
    return {"points": thin(points, CHART_POINTS), "log_scale": cfg.log_scale}


def drawdown_chart(env: Env, cfg: Any) -> dict[str, Any]:
    ctx = context(env, account_of(cfg, env))
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
    ctx = context(env, account_of(cfg, env))
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


def allocation(env: Env, cfg: Any) -> dict[str, Any]:
    if cfg.look_through:
        return {
            "unavailable": True,
            "reason": "Look-through needs ETF holdings data, planned for Phase 4.",
        }
    ctx = context(env, account_of(cfg, env))
    result, unvalued = svc.allocation_at(env.db, ctx, env.today, cfg.group_by)
    if result.total_eur == 0 and not result.slices:
        return _empty("Add a holding to see how your portfolio is divided.")
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


def drift_bars(env: Env, cfg: Any) -> dict[str, Any]:
    ctx = context(env, account_of(cfg, env))
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


def holdings_table(env: Env, cfg: Any) -> dict[str, Any]:
    rows, totals = load_positions(env.db, account_id=account_of(cfg, env), today=env.today)
    if not rows:
        return _empty("Add your first instrument and a transaction to see positions here.")
    meta = svc.load_meta(env.db, {r.instrument.id for r in rows})
    out = []
    for r in rows:
        m = r.metrics
        out.append(
            {
                "instrument_id": r.instrument.id,
                "name": r.instrument.name,
                "account": r.account.name,
                "asset_class": r.instrument.asset_class,
                "sleeve": meta[r.instrument.id].sleeve if r.instrument.id in meta else None,
                "quantity": str(r.state.quantity),
                "avg_cost_eur": s(r.state.avg_cost_eur),
                "cost_basis_eur": str(r.state.cost_basis_eur),
                "close": s(r.price.close if r.price else None),
                "close_date": None if r.price is None else r.price.date.isoformat(),
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
    account = account_of(cfg, env)
    ctx = context(env, account)
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
    ctx = context(env, account_of(cfg, env))
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
    ctx = context(env, account_of(cfg, env))
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


def income(env: Env, cfg: Any) -> dict[str, Any]:
    account = account_of(cfg, env)
    ctx = context(env, account)
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


def price_chart(env: Env, cfg: Any) -> dict[str, Any]:
    instrument_id = cfg.instrument_id or (cfg.scope.id if cfg.scope.kind == "instrument" else None)
    if instrument_id is None:
        return _empty("Choose an instrument for this chart.")
    instrument = env.db.get(Instrument, instrument_id)
    if instrument is None or instrument.deleted_at is not None:
        raise WidgetDataError("That instrument no longer exists.")
    listing = env.db.scalars(
        select(Listing)
        .where(Listing.instrument_id == instrument_id)
        .order_by(Listing.pricing_primary.desc(), Listing.id)
        .limit(1)
    ).first()
    if listing is None:
        return _empty("This instrument has no listing to chart.")
    ctx = context(env, None)
    first_day = ctx.first_transaction_day
    try:
        start, end = (
            svc.resolve(ctx, period_of(cfg, env, "1Y"), env.today)
            if not ctx.empty
            else (env.today - timedelta(days=365), env.today)
        )
    except ValueError as exc:
        raise WidgetDataError(str(exc)) from exc
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
    if "trades" in cfg.overlays:
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
    out: dict[str, Any] = {
        "instrument_id": instrument_id,
        "name": instrument.name,
        "currency": listing.currency,
        "chart": cfg.chart,
        "first_transaction": None if first_day is None else first_day.isoformat(),
        "points": thin(
            [
                {
                    "date": b.date.isoformat(),
                    "open": s(b.open),
                    "high": s(b.high),
                    "low": s(b.low),
                    "close": str(b.close),
                    "volume": s(b.volume),
                }
                for b in shown
            ],
            CHART_POINTS,
        ),
        "trades": trades,
    }  # fmt: skip
    for key, n in (("ma50", 50), ("ma200", 200)):
        if key in cfg.overlays:
            out[key] = [p for p in _moving_average(closes, n) if p["date"] > start.isoformat()]
    return out


def performance(env: Env, cfg: Any) -> dict[str, Any]:
    refs = list(cfg.series)
    if not refs:
        refs = [{"kind": "portfolio", "id": None}] + [
            {"kind": "benchmark", "id": i} for i in svc.benchmark_ids(env.db)
        ]
    else:
        refs = [r.model_dump() for r in refs]
    price_ids = [
        r["id"] for r in refs if r["kind"] in ("benchmark", "instrument") and r["id"] is not None
    ]
    ctx = context(env, account_of(cfg, env), price_ids)
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


# --- widgets whose data arrives in later phases --------------------------------------------------


def _later(reason: str) -> Callable[[Env, Any], dict[str, Any]]:
    def build(env: Env, cfg: Any) -> dict[str, Any]:
        return {"unavailable": True, "reason": reason}

    return build


def note(env: Env, cfg: Any) -> dict[str, Any]:
    return {"text": cfg.text}


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
    "look_through": _later("Look-through needs the holdings of your ETFs (Phase 4)."),
    "correlation_matrix": correlation,
    "drawdown": drawdown_chart,
    "return_bridge": return_bridge,
    "income": income,
    "macro_overlay": _later("Macro indicators arrive with the strategies in Phase 3."),
    "news_feed": _later("News arrives in Phase 4."),
    "signals": _later("Recommendations and alerts arrive in Phase 3."),
    "note": note,
}


def compute(env: Env, kind: str, config: dict[str, Any]) -> dict[str, Any]:
    widget = WIDGET_TYPES.get(kind)
    if widget is None:
        raise WidgetDataError(f"Unknown widget type {kind!r}.")
    return COMPUTE[kind](env, widget.config.model_validate(config))
