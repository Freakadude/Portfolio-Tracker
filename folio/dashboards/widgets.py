"""The widget library (spec section 9): each widget type, the options it accepts and its default
size. The server validates what the browser saves, so a dashboard that is stored, exported and
imported can always be drawn."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Period = Literal["1D", "1W", "1M", "3M", "YTD", "1Y", "3Y", "5Y", "MAX"]
Grouping = Literal[
    "instrument", "asset_class", "sleeve", "region", "sector", "currency", "company", "country"
]
KPI_METRICS = (
    "value",
    "day_change",
    "total_return",
    "period_return",
    "twr",
    "xirr",
    "cash",
    "net_contributions",
    "income",
    "largest_drift",
    "volatility",
    "max_drawdown",
    "current_drawdown",
    "sharpe",
    "beta",
)


class Scope(BaseModel):
    """What a widget looks at: the whole portfolio, or one account, sleeve, instrument or
    watchlist."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["portfolio", "account", "sleeve", "instrument", "watchlist"] = "portfolio"
    id: int | None = None


class BaseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=100)
    scope: Scope = Field(default_factory=Scope)
    period: Period | None = None  # None: follow the dashboard's period
    follow_filters: bool = True  # False: ignore the dashboard's period and account


class KpiConfig(BaseConfig):
    metric: Literal[
        "value", "day_change", "total_return", "period_return", "twr", "xirr", "cash",
        "net_contributions", "income", "largest_drift", "volatility", "max_drawdown",
        "current_drawdown", "sharpe", "beta",
    ] = "value"  # fmt: skip
    sparkline: bool = True


class ValueHistoryConfig(BaseConfig):
    log_scale: bool = False


Overlay = Literal["ma50", "ma200", "volume", "trades"]


def _default_overlays() -> list[Overlay]:
    return ["trades"]


class PriceChartConfig(BaseConfig):
    instrument_id: int | None = None
    chart: Literal["line", "candles"] = "line"
    overlays: list[Overlay] = Field(default_factory=_default_overlays)


class SeriesRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["portfolio", "benchmark", "instrument", "sleeve"]
    id: int | None = None


class PerformanceConfig(BaseConfig):
    # Empty: the portfolio and the instruments flagged as benchmarks
    series: list[SeriesRef] = Field(default_factory=list, max_length=6)


class AllocationConfig(BaseConfig):
    group_by: Grouping = "asset_class"
    chart: Literal["donut", "treemap"] = "donut"
    show_target: bool = True
    look_through: bool = False  # open ETFs up into what they hold (FR-PF-05)


class DriftBarsConfig(BaseConfig):
    pass


class HoldingsTableConfig(BaseConfig):
    columns: list[str] = Field(
        default_factory=lambda: ["name", "quantity", "value", "weight", "unrealized", "day"]
    )
    group_by: Literal["none", "account", "sleeve", "asset_class"] = "none"
    sort_by: str | None = None  # a column key; None keeps the order of the list
    sort_dir: Literal["asc", "desc"] = "desc"


class HeatmapConfig(BaseConfig):
    pass


class MonthlyReturnsConfig(BaseConfig):
    pass


class LookThroughConfig(BaseConfig):
    dimension: Literal["company", "country", "sector", "currency"] = "company"
    top_n: int = Field(default=20, ge=1, le=100)


class CorrelationConfig(BaseConfig):
    window: Literal["90D", "1Y"] = "1Y"


class DrawdownConfig(BaseConfig):
    pass


class BridgeConfig(BaseConfig):
    pass


class AttributionConfig(BaseConfig):
    pass


class IncomeConfig(BaseConfig):
    pass


class MacroConfig(BaseConfig):
    """Up to two indicator series, each in its own pane, and optionally one position's price
    rebased to 100 below them: one shared time axis, never two y-scales."""

    series_code: str | None = Field(default=None, max_length=80)  # default: the first stored
    second_code: str | None = Field(default=None, max_length=80)
    instrument_id: int | None = None


class NewsConfig(BaseConfig):
    min_impact: int = Field(default=0, ge=0, le=100)


class SignalsConfig(BaseConfig):
    severity: Literal["all", "low", "medium", "high", "critical"] = "all"  # at least this


class ProjectionConfig(BaseConfig):
    years: int = Field(default=20, ge=1, le=40)
    monthly_contribution: Decimal = Field(default=Decimal(0), ge=0, le=1_000_000)
    return_pct: Decimal = Field(default=Decimal(5), ge=-50, le=50)
    volatility_pct: Decimal = Field(default=Decimal(15), ge=0, le=100)


class AskConfig(BaseConfig):
    show_last: int = Field(default=3, ge=1, le=10)  # how many earlier answers stay on the widget


class NoteConfig(BaseConfig):
    text: str = Field(default="", max_length=5000)


@dataclass(frozen=True)
class WidgetType:
    key: str
    config: type[BaseConfig]
    width: int  # default size on the 12-column grid
    height: int
    title_key: str  # the i18n key of its name in the library


WIDGET_TYPES: dict[str, WidgetType] = {
    t.key: t
    for t in (
        WidgetType("kpi", KpiConfig, 3, 3, "widgets.kpi"),
        WidgetType("value_history", ValueHistoryConfig, 8, 6, "widgets.value_history"),
        WidgetType("price_chart", PriceChartConfig, 8, 5, "widgets.price_chart"),
        WidgetType("performance_comparison", PerformanceConfig, 8, 5, "widgets.performance"),
        WidgetType("allocation", AllocationConfig, 4, 7, "widgets.allocation"),
        WidgetType("drift_bars", DriftBarsConfig, 6, 4, "widgets.drift_bars"),
        WidgetType("holdings_table", HoldingsTableConfig, 12, 6, "widgets.holdings_table"),
        WidgetType("returns_heatmap", HeatmapConfig, 6, 4, "widgets.returns_heatmap"),
        WidgetType("monthly_returns", MonthlyReturnsConfig, 8, 5, "widgets.monthly_returns"),
        WidgetType("look_through", LookThroughConfig, 6, 5, "widgets.look_through"),
        WidgetType("correlation_matrix", CorrelationConfig, 6, 6, "widgets.correlation"),
        WidgetType("drawdown", DrawdownConfig, 8, 4, "widgets.drawdown"),
        WidgetType("return_bridge", BridgeConfig, 8, 5, "widgets.return_bridge"),
        WidgetType("attribution", AttributionConfig, 6, 5, "widgets.attribution"),
        WidgetType("income", IncomeConfig, 8, 4, "widgets.income"),
        WidgetType("macro_overlay", MacroConfig, 8, 5, "widgets.macro_overlay"),
        WidgetType("news_feed", NewsConfig, 6, 6, "widgets.news_feed"),
        WidgetType("signals", SignalsConfig, 6, 6, "widgets.signals"),
        WidgetType("projection", ProjectionConfig, 8, 6, "widgets.projection"),
        WidgetType("ask", AskConfig, 6, 7, "widgets.ask"),
        WidgetType("note", NoteConfig, 4, 3, "widgets.note"),
    )
}


class WidgetError(ValueError):
    """A widget type or its configuration is not valid; the message says what to change."""


def normalize_config(kind: str, config: dict[str, Any] | None) -> dict[str, Any]:
    """Validate a widget's options and return them complete, with defaults filled in."""
    widget = WIDGET_TYPES.get(kind)
    if widget is None:
        raise WidgetError(
            f"Unknown widget type {kind!r}. Choose one of: {', '.join(WIDGET_TYPES)}."
        )
    try:
        return widget.config.model_validate(config or {}).model_dump(mode="json")
    except ValueError as exc:
        raise WidgetError(f"The {kind} widget has an option that is not valid: {exc}") from exc
