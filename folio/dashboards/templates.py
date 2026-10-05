"""The four ready-made dashboards (FR-DB-07). Each is a list of widgets with their desktop
position; tablet and phone layouts are derived from it. Every template works on an empty
portfolio: widgets show an empty state that says what to do."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TemplateWidget:
    type: str
    x: int
    y: int
    w: int
    h: int
    config: dict[str, Any]


@dataclass(frozen=True)
class Template:
    key: str
    name: str
    description: str
    widgets: tuple[TemplateWidget, ...]


def _kpi(metric: str, x: int, y: int = 0) -> TemplateWidget:
    return TemplateWidget("kpi", x, y, 3, 2, {"metric": metric})


TEMPLATES: dict[str, Template] = {
    t.key: t
    for t in (
        Template(
            "overview",
            "Overview",
            "Value, result, allocation and your holdings at a glance.",
            (
                _kpi("value", 0),
                _kpi("total_return", 3),
                _kpi("day_change", 6),
                _kpi("xirr", 9),
                TemplateWidget("value_history", 0, 2, 8, 5, {}),
                TemplateWidget("allocation", 8, 2, 4, 5, {"group_by": "asset_class"}),
                TemplateWidget("holdings_table", 0, 7, 12, 6, {}),
            ),
        ),
        Template(
            "risk",
            "Risk",
            "Volatility, drawdown, Sharpe ratio, beta and how your holdings move together.",
            (
                _kpi("volatility", 0),
                _kpi("max_drawdown", 3),
                _kpi("sharpe", 6),
                _kpi("beta", 9),
                TemplateWidget("drawdown", 0, 2, 12, 4, {}),
                TemplateWidget("correlation_matrix", 0, 6, 6, 6, {"window": "1Y"}),
                TemplateWidget("performance_comparison", 6, 6, 6, 6, {}),
            ),
        ),
        Template(
            "income",
            "Income",
            "Dividends and interest by month, and what each position returned.",
            (
                _kpi("income", 0),
                _kpi("net_contributions", 3),
                _kpi("total_return", 6),
                _kpi("value", 9),
                TemplateWidget("income", 0, 2, 12, 5, {}),
                TemplateWidget("return_bridge", 0, 7, 8, 5, {}),
                TemplateWidget("allocation", 8, 7, 4, 5, {"group_by": "instrument"}),
            ),
        ),
        Template(
            "signals",
            "Signals & news",
            "Recommendations, alerts and linked news. These arrive in later phases.",
            (
                TemplateWidget("signals", 0, 0, 6, 6, {}),
                TemplateWidget("news_feed", 6, 0, 6, 6, {}),
                TemplateWidget(
                    "note",
                    0,
                    6,
                    12,
                    2,
                    {
                        "text": (
                            "Strategies, alerts and news are built in later phases; "
                            "this dashboard fills up then."
                        )
                    },
                ),
            ),
        ),
    )
}
