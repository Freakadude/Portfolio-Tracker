"""What the owner sees on screen, read for the chat helper (ADR 0059, FR-AG-08).

The dashboard widgets already have one tested source of numbers (`dashboards/data.py`), so the
helper reads the same: `widget_data` runs a widget exactly as the page would, `dashboard_view`
runs every widget of one dashboard. Two things are added on the way to the model:

* In privacy mode (the default) every euro amount of the owner's money is taken out
  (`private`), as it is for the other tools; percentages, weights, dates, quantities and
  per-unit prices stay.
* Long series are cut to a sample with their low and high (`compact`), so one result is small.

Text that came from outside, or that the owner typed, is wrapped as untrusted data.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from folio.agent.text import untrusted
from folio.dashboards import service as dashboards
from folio.dashboards.data import Env, Filters, WidgetDataError, compute, thin
from folio.dashboards.widgets import WidgetError, normalize_config
from folio.db.models_analytics import Dashboard

SAMPLE = 24  # points of a series that one tool result carries
VIEW_SAMPLE = 12  # and in the view of a whole dashboard, where there are many widgets
VIEW_WIDGETS = 10  # widgets of a dashboard whose data is included (the rest are listed)
MAX_ROWS = 60
HIDDEN = "Euro amounts are hidden because privacy mode is on (Settings, Agent)."

# the widgets the helper can read: a name as the owner sees it, and what it shows and is for
WIDGETS: dict[str, tuple[str, str]] = {
    "kpi": (
        "Key figure",
        "One headline figure of the portfolio, a sleeve or one holding for a period, such as "
        "value, return, volatility, maximum drawdown or the latest price.",
    ),
    "value_history": (
        "Value over time",
        "How the portfolio's value and the money put in have developed; the gap between the two "
        "lines is the result.",
    ),
    "price_chart": (
        "Price chart",
        "The price of one holding over a period, optionally with moving averages, the owner's "
        "buys and sells and the change over the period.",
    ),
    "price_history": (
        "Price history",
        "The price of up to six holdings over one period: the day's refresh prices for one day, "
        "otherwise the daily closes.",
    ),
    "performance_comparison": (
        "Performance comparison",
        "The portfolio's time-weighted return against benchmarks or holdings, all starting at "
        "100, so growth can be compared.",
    ),
    "allocation": (
        "Allocation",
        "How the portfolio is divided by asset class, sleeve, region, sector or currency, with "
        "targets and drift where sleeves have them.",
    ),
    "drift_bars": (
        "Drift from target",
        "How far each sleeve is from its target weight, in percentage points, and whether it is "
        "outside its band.",
    ),
    "holdings_table": (
        "Holdings",
        "One line per holding: quantity, price, weight and result.",
    ),
    "returns_heatmap": (
        "Returns heatmap",
        "The return of every position over a period, so the best and worst stand out.",
    ),
    "monthly_returns": (
        "Monthly returns",
        "The portfolio's time-weighted return month by month and year by year.",
    ),
    "look_through": (
        "Look-through",
        "What the portfolio holds underneath its ETFs: the largest companies, countries, sectors "
        "or currencies, with ETFs opened up into their holdings.",
    ),
    "correlation_matrix": (
        "Correlation",
        "How closely pairs of holdings move together (1 together, 0 unrelated, -1 opposite); low "
        "values mean better diversification.",
    ),
    "drawdown": (
        "Drawdown",
        "How far the portfolio is below its previous high at each date, as a negative "
        "percentage. The deepest point is the maximum drawdown, today's value is the current "
        "drawdown, and the dates give how long a fall lasted. It shows the pain of the worst "
        "stretch the owner would have lived through, so it helps to judge risk tolerance.",
    ),
    "return_bridge": (
        "Return bridge",
        "A step-by-step bridge from the value at the start of a period to the value at the end: "
        "money put in, and what each holding gained or lost.",
    ),
    "attribution": (
        "Attribution",
        "What each position contributed to the period's result, in points of return.",
    ),
    "income": (
        "Income",
        "Dividends and interest received, month by month.",
    ),
    "macro_overlay": (
        "Macro indicators",
        "One or two macro indicator series (such as interest rates), optionally next to a "
        "holding's price rebased to the same start.",
    ),
    "news_feed": (
        "News",
        "The latest stories linked to what the owner holds, with their assessed impact.",
    ),
    "signals": (
        "Signals",
        "What is waiting for the owner: open recommendations and the signals the strategy's "
        "rules raised.",
    ),
    "projection": (
        "Projection",
        "A what-if projection of the portfolio's future value with the widget's own assumptions "
        "(return, volatility, monthly saving); a range, not a forecast.",
    ),
    "ask": ("Ask box", "A box for questions to the AI helper."),
    "note": ("Note", "A note the owner wrote."),
}

# pages that are not dashboards: what is on them and the tools that read it
PAGES: dict[str, tuple[str, list[str]]] = {
    "holdings": (
        "the holdings list",
        ["get_positions", "get_allocation", "get_widget (holdings_table)"],
    ),
    "transactions": ("the transactions", ["get_transactions"]),
    "insights": (
        "the insights page: recommendations, open signals and the inbox",
        ["get_recommendation_history", "get_signals", "get_inbox", "get_widget (signals)"],
    ),
    "news": ("the news page", ["get_news"]),
    "strategies": ("the strategies page", ["get_strategy", "get_portfolio_summary"]),
    "watchlist": ("the watchlist", ["get_watchlist"]),
    "reports": ("the reports", ["get_widget (monthly_returns, attribution, income)"]),
    "what-if": ("the what-if simulator", ["simulate"]),
    "settings": ("the settings", []),
    "system": ("the system page", []),
}


class ViewError(ValueError):
    """The page cannot be read; the message goes back to the model."""


# --- privacy and size -----------------------------------------------------------------------------


def _drop_eur(node: Any) -> Any:
    """Every field whose name ends in _eur, at any depth: those are euro amounts."""
    if isinstance(node, dict):
        return {k: _drop_eur(v) for k, v in node.items() if not str(k).endswith("_eur")}
    if isinstance(node, list):
        return [_drop_eur(v) for v in node]
    return node


def _only(data: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: data[k] for k in keys if k in data}


def private(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    """A widget's data without any euro amount of the owner's money (privacy mode). Widgets that
    are only euro amounts say so instead; the ones with a ratio keep it."""
    if data.get("empty"):
        return data
    if kind == "kpi":
        out = dict(data)
        if data.get("kind") == "eur":
            out["value"], out["hidden"] = None, HIDDEN
        if data.get("metric") != "latest_price" or data.get("kind") == "eur":
            out["sparkline"] = []
        out.pop("breakdown", None)  # the steps behind a return are euro flows
        return _drop_eur(out)  # type: ignore[no-any-return]
    if kind == "holdings_table":
        euro = {"value", "unrealized", "day", "total_return", "income"}
        out = dict(data)
        out["rows"] = [{k: v for k, v in row.items() if k not in euro} for row in data["rows"]]
        out["totals"] = _only(data.get("totals") or {}, "unrealized_ratio")
        return _drop_eur(out)  # type: ignore[no-any-return]
    if kind in ("value_history", "return_bridge", "income"):
        kept = _only(data, "start", "end", "period", "unpriced_before", "unpriced_days")
        return {**kept, "hidden": HIDDEN}
    if kind == "projection":
        assumptions = _only(
            data.get("assumptions") or {}, "annual_return_pct", "annual_volatility_pct", "years"
        )
        return {"assumptions": assumptions, "hidden": HIDDEN}
    return _drop_eur(data)  # type: ignore[no-any-return]


def _number(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _series(points: list[dict[str, Any]], sample: int) -> dict[str, Any]:
    """A long dated series as a sample (first and last kept) with its low and high."""
    out: dict[str, Any] = {"count": len(points), "sample": thin(points, sample)}
    key = next((k for k in ("value", "close", "price") if all(k in p for p in points)), None)
    if key is not None:
        numbered = [(n, p) for p in points if (n := _number(p[key])) is not None]
        if numbered:
            for label, pick in (("low", min), ("high", max)):
                n, p = pick(numbered, key=lambda item: item[0])
                out[label] = {"date": p.get("date") or p.get("time"), key: str(n)}
    return out


def _tidy(text: str) -> str:
    """A long decimal string without the arithmetic noise: -4E-40 is 0, 0.0523000000001 is
    0.0523. Text that is not a number is left as it is."""
    if "E" not in text and "e" not in text and len(text.rpartition(".")[2]) <= 8:
        return text
    number = _number(text)
    if number is None:
        return text
    rounded = number.quantize(Decimal("0.00000001"))
    return "0" if rounded == 0 else format(rounded.normalize(), "f")


def compact(node: Any, sample: int = SAMPLE) -> Any:
    if isinstance(node, str):
        return _tidy(node)
    if isinstance(node, dict):
        return {k: compact(v, sample) for k, v in node.items()}
    if isinstance(node, list):
        dated = bool(node) and all(
            isinstance(p, dict) and ("date" in p or "time" in p) for p in node
        )
        if dated and len(node) > sample:
            return _series(node, sample)
        return [compact(v, sample) for v in node[:MAX_ROWS]]
    return node


def _outside(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    """Text the owner typed or a news source wrote is data, not instructions."""
    out = dict(data)
    if kind == "note" and isinstance(out.get("text"), str):
        out["text"] = untrusted(out["text"])
    if kind == "news_feed" and isinstance(out.get("stories"), list):
        out["stories"] = [
            {**s, "title": untrusted(str(s.get("title", "")))} for s in out["stories"]
        ]
    return out


# --- reading --------------------------------------------------------------------------------------


def filters_of(saved: dict[str, Any] | None) -> Filters:
    """The dashboard's saved period, account and holding filters as the widgets read them."""
    saved = saved or {}

    def day(value: Any) -> dt.date | None:
        try:
            return dt.date.fromisoformat(str(value)) if value else None
        except ValueError:
            return None

    def ints(value: Any) -> tuple[int, ...]:
        return tuple(int(v) for v in value or [] if str(v).lstrip("-").isdigit())

    account = saved.get("account")
    period = saved.get("period")
    return Filters(
        period if isinstance(period, str) else None,
        account if isinstance(account, int) and not isinstance(account, bool) else None,
        day(saved.get("start")),
        day(saved.get("end")),
        tuple(str(t) for t in saved.get("types") or []),
        ints(saved.get("instruments")),
    )


def widget_data(
    db: Session,
    today: dt.date,
    kind: str,
    options: dict[str, Any],
    filters: Filters,
    privacy: bool,
    sample: int = SAMPLE,
) -> dict[str, Any]:
    """One widget's data as the page computes it. Raises what the owner would be told."""
    try:
        config = normalize_config(kind, options)
        data = compute(Env(db, today, filters), kind, config)
    except (WidgetError, WidgetDataError) as exc:
        raise ViewError(str(exc)) from exc
    if privacy:
        data = private(kind, data)
    return compact(_outside(kind, data), sample)  # type: ignore[no-any-return]


def _default_dashboard(db: Session) -> Dashboard | None:
    live = dashboards.list_dashboards(db)
    return next((d for d in live if d.is_default), live[0] if live else None)


def dashboard_view(
    db: Session, today: dt.date, dashboard: Dashboard, privacy: bool
) -> dict[str, Any]:
    """Everything a dashboard shows: its filters, and for each widget its type, options, what it
    is for and its data (the first widgets; the rest only listed, to be read with get_widget)."""
    filters = filters_of(dashboard.filters)
    shown: list[dict[str, Any]] = []
    for n, widget in enumerate(dashboards.widgets_of(db, dashboard.id)):
        name, about = WIDGETS.get(widget.type, (widget.type, ""))
        config = dict(widget.config or {})
        entry: dict[str, Any] = {
            "widget": widget.type,
            "title": str(config.get("title") or name),
            "about": about,
            "options": {k: v for k, v in config.items() if k not in ("title", "text")},
        }
        if widget.type in ("ask", "note") or n >= VIEW_WIDGETS:
            if widget.type == "note":
                entry["data"] = _outside("note", {"text": str(config.get("text") or "")})
            elif widget.type != "ask":
                entry["data"] = "Not included here: read it with get_widget."
            shown.append(entry)
            continue
        try:
            entry["data"] = widget_data(
                db, today, widget.type, config, filters, privacy, VIEW_SAMPLE
            )
        except ViewError as exc:
            entry["error"] = str(exc)
        shown.append(entry)
    return {
        "dashboard": {
            "id": dashboard.id,
            "name": dashboard.name,
            "is_default": dashboard.is_default,
        },
        "filters": {
            "period": filters.period,
            "account": filters.account,
            "start": filters.start and filters.start.isoformat(),
            "end": filters.end and filters.end.isoformat(),
            "types": list(filters.types),
            "instruments": list(filters.instruments),
        },
        "widgets": shown,
    }


def page_view(db: Session, today: dt.date, page: str | None, privacy: bool) -> dict[str, Any]:
    """The dashboard the route names, or for any other page what it shows and which tools read
    it. Position pages are completed by the caller, which owns the position tool."""
    parts = [p for p in (page or "").split("?", 1)[0].split("/") if p]
    if not parts or (parts[0] == "dashboards" and len(parts) == 2 and parts[1].isdigit()):
        if parts:
            found = db.get(Dashboard, int(parts[1]))
            dashboard = found if found is not None and found.deleted_at is None else None
        else:
            dashboard = _default_dashboard(db)
        if dashboard is None:
            raise ViewError("That dashboard does not exist." if parts else "There is no dashboard.")
        return {"page": "/" + "/".join(parts), **dashboard_view(db, today, dashboard, privacy)}
    if parts[0] == "dashboards":
        return {
            "page": "/dashboards",
            "about": "the list of dashboards",
            "dashboards": [
                {"id": d.id, "name": d.name, "is_default": d.is_default}
                for d in dashboards.list_dashboards(db)
            ],
            "use": ["get_view with page '/dashboards/<id>' reads one of them"],
        }
    about, use = PAGES.get(parts[0], ("a page of the app", []))
    return {"page": "/" + "/".join(parts), "about": about, "use": use}
