"""A starting point for a new strategy (spec appendix B), built from the owner's own sleeves.

Every target and threshold is left empty (owner decision Q3): the rules that need a number
stay silent until one is filled in. Rule parameters are illustrative starting values.
"""

from __future__ import annotations

from collections.abc import Sequence

PRINCIPLES = (
    "Rebalance by directing new contributions to underweight sleeves before considering any sale.",
    "No emotionally driven profit-taking; trims happen only at pre-committed thresholds.",
)


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def starter_yaml(name: str, sleeves: Sequence[tuple[str, Sequence[str]]]) -> str:
    """YAML for a new strategy with these sleeves (name, member ISINs). Without sleeves it
    gets one example sleeve to show the shape."""
    lines = [
        "strategy:",
        f"  name: {_quote(name)}",
        "  base_currency: EUR",
        "  principles:",
        *[f"    - {_quote(p)}" for p in PRINCIPLES],
        "  prefer_buys: true",
        "  macro_series:",
        "    US_REAL_YIELD_10Y: { source: fred, code: DFII10 }      # 10-year TIPS real yield",
        "    USD_TRADE_WEIGHTED: { source: fred, code: DTWEXBGS }   # broad trade-weighted dollar",
        "  sleeves:",
    ]
    for sleeve_id, members in sleeves or [("core", [])]:
        member_list = ", ".join(members)
        lines.append(
            f"    - {{ id: {_quote(sleeve_id)}, members: [{member_list}], target_pct: null, "
            "soft_band_pp: null, hard_band_pp: null }"
        )
    lines += [
        "  risk_limits:",
        "    max_single_company_lookthrough_pct: null",
        "    max_thematic_total_pct: null",
        "  rules:",
        "    - { id: drift, type: drift_band, applies_to: all, severity: medium,"
        " cooldown_days: 7 }",
        "    - { id: trims, type: trim_threshold, applies_to: all, severity: high,"
        " cooldown_days: 14 }",
        "    - { id: drawdown, type: drawdown, scope: position, threshold_pct: 20,"
        " severity: medium, cooldown_days: 14 }",
        "    - { id: real_yield, type: macro_threshold, series: US_REAL_YIELD_10Y, change_bp: 50,"
        " window_days: 30, severity: low }",
        "    - { id: stale, type: stale_data, severity: high, cooldown_days: 1 }",
        "    - { id: reviews, type: thesis_review_due, severity: low, cooldown_days: 30 }",
        "  theses: []",
        "",
    ]
    return "\n".join(lines)
