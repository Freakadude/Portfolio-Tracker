"""Every rule type against hand-made inputs, the waiting reasons, and the push texts (FR-ST-03,
FR-ST-04, FR-NT-07)."""

import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from folio.analytics.lookthrough import Exposure, Part
from folio.strategies.rules import (
    PositionState,
    RuleInputs,
    SleeveState,
    evaluate,
    next_contribution,
)
from folio.strategies.schema import StrategyDef
from folio.strategies.signals import Open, should_fire

D = Decimal
TODAY = date(2025, 3, 14)  # a Friday


def strategy(**over: Any) -> StrategyDef:
    base: dict[str, Any] = {
        "name": "Test",
        "macro_series": {"RY": {"source": "fred", "code": "DFII10"}},
        "sleeves": [
            {
                "id": "equity",
                "target_pct": 60,
                "soft_band_pp": 5,
                "hard_band_pp": 10,
                "trim_threshold_pct": 75,
            },
            {"id": "gold", "target_pct": 40, "soft_band_pp": 5, "hard_band_pp": 10},
            {"id": "bonds"},  # no target yet (Q3)
        ],
        "rules": [],
    }
    base.update(over)
    return StrategyDef.model_validate(base)


def closes(values: list[str | int], end: date = TODAY) -> list[tuple[date, Decimal]]:
    start = end - timedelta(days=len(values) - 1)
    return [(start + timedelta(days=i), D(str(v))) for i, v in enumerate(values)]


def position(
    name: str = "Acme", values: list[str | int] | None = None, **over: Any
) -> PositionState:
    fields: dict[str, Any] = {
        "instrument_id": 1,
        "name": name,
        "isin": "IE00B5BMR087",
        "sleeve": "equity",
        "weight": D("0.5"),
        "closes_eur": closes(values or [100, 100]),
        "close": D(str((values or [100])[-1])),
        "currency": "EUR",
    }
    fields.update(over)
    return PositionState(**fields)


def inputs(**over: Any) -> RuleInputs:
    fields: dict[str, Any] = {
        "today": TODAY,
        "total_eur": D(1000),
        "sleeves": {"equity": SleeveState(D("0.6"), D(600)), "gold": SleeveState(D("0.4"), D(400))},
        "positions": [],
        "portfolio_index": [],
        "sleeve_returns": {},
        "macro": {},
        "stale": [],
        "tracked_cash_eur": None,
        "strategy_since": TODAY - timedelta(days=30),
    }
    fields.update(over)
    return RuleInputs(**fields)


def run(rules: list[dict[str, Any]], x: RuleInputs | None = None, **over: Any):  # type: ignore[no-untyped-def]
    return evaluate(strategy(rules=rules, **over), x or inputs())


def drift_inputs(equity: str) -> RuleInputs:
    w = D(equity)
    return inputs(
        sleeves={"equity": SleeveState(w, w * 1000), "gold": SleeveState(1 - w, (1 - w) * 1000)}
    )


# --- drift and trim -----------------------------------------------------------------------------


def test_inside_the_band_nothing_fires() -> None:
    assert run([{"id": "d", "type": "drift_band"}], drift_inputs("0.64")).findings == []


def test_a_soft_breach_advises_new_money_a_hard_breach_a_trade() -> None:
    soft = run(
        [{"id": "d", "type": "drift_band", "severity": "medium"}], drift_inputs("0.67")
    ).findings
    assert [(f.subject, f.severity, f.variant) for f in soft] == [
        ("equity", "medium", "soft"),
        ("gold", "medium", "soft"),
    ]
    assert "Direct new money" in soft[0].message and soft[0].value == D("7.0")
    hard = run(
        [{"id": "d", "type": "drift_band", "severity": "medium"}], drift_inputs("0.72")
    ).findings
    assert [(f.severity, f.variant) for f in hard] == [("high", "hard"), ("high", "hard")]
    assert "trade" in hard[0].message
    assert hard[0].dedup_key == "d:equity:hard" != soft[0].dedup_key


def test_a_sleeve_without_a_target_never_fires_and_says_why() -> None:
    no_targets = [{"id": "bonds"}]
    result = run([{"id": "d", "type": "drift_band"}], drift_inputs("0.9"), sleeves=no_targets)
    assert result.findings == []
    assert result.statuses[0].reason == "No sleeve has a target and a band yet."


def test_drift_can_be_limited_to_some_sleeves() -> None:
    found = run(
        [{"id": "d", "type": "drift_band", "applies_to": ["gold"]}], drift_inputs("0.72")
    ).findings
    assert [f.subject for f in found] == ["gold"]


def test_trim_fires_above_the_threshold_only() -> None:
    rule = [{"id": "t", "type": "trim_threshold", "severity": "high"}]
    assert run(rule, drift_inputs("0.75")).findings == []
    (f,) = run(rule, drift_inputs("0.76")).findings
    assert (f.subject, f.severity, f.value) == ("equity", "high", D("76.00"))


# --- drawdowns and moves -------------------------------------------------------------------------


def test_a_position_drawdown_asks_for_a_review_not_a_sale() -> None:
    x = inputs(positions=[position(values=[100, 120, 90])])
    (f,) = run([{"id": "dd", "type": "drawdown", "threshold_pct": 20}], x).findings
    assert f.value == D(25) and "not a reason to sell" in f.message
    assert run([{"id": "dd", "type": "drawdown", "threshold_pct": 30}], x).findings == []


def test_a_portfolio_drawdown_uses_the_time_weighted_index() -> None:
    x = inputs(portfolio_index=closes(["1", "1.2", "1.02"]))
    (f,) = run(
        [{"id": "dd", "type": "drawdown", "scope": "portfolio", "threshold_pct": 15}], x
    ).findings
    assert f.subject == "portfolio" and f.value == D(15)


def test_a_daily_move_fires_by_percent_or_by_standard_deviations() -> None:
    calm = [100 + (i % 2) for i in range(40)]  # +-1% wiggles
    x = inputs(positions=[position(values=[*calm, 105])])
    assert run([{"id": "m", "type": "price_move", "pct": 5}], x).findings == []
    (f,) = run([{"id": "m", "type": "price_move", "pct": 3}], x).findings
    assert "moved up" in f.title and f.variant == TODAY.isoformat()
    (g,) = run([{"id": "m", "type": "price_move", "sigma": 3}], x).findings
    assert g.subject == "Acme"
    old = inputs(
        positions=[
            position(values=[100, 110], closes_eur=closes([100, 110], TODAY - timedelta(days=10)))
        ]
    )
    assert run([{"id": "m", "type": "price_move", "pct": 3}], old).findings == []  # not today's


def test_a_price_level_fires_on_the_right_side() -> None:
    x = inputs(positions=[position(values=[100, 131])])
    rule = {"id": "lvl", "type": "price_level", "instrument": "IE00B5BMR087", "above": 130}
    (f,) = run([rule], x).findings
    assert f.variant == "above" and "131" in f.message
    assert run([{**rule, "above": 140}], x).findings == []
    assert run([{**rule, "instrument": "IE00B4ND3602"}], x).findings == []


# --- macro and correlation ----------------------------------------------------------------------


def test_a_macro_series_fires_on_a_move_or_a_level() -> None:
    series = closes(["1.50"] * 31 + ["2.05"])
    x = inputs(macro={"RY": series})
    (f,) = run(
        [
            {
                "id": "ry",
                "type": "macro_threshold",
                "series": "RY",
                "change_bp": 50,
                "applies_to": ["gold"],
            }
        ],
        x,
    ).findings
    assert "moved 55 bp" in f.title and "concerns gold" in f.message and f.value == D(55)
    assert (
        run([{"id": "ry", "type": "macro_threshold", "series": "RY", "change_bp": 60}], x).findings
        == []
    )
    (lvl,) = run([{"id": "ry", "type": "macro_threshold", "series": "RY", "above": 2}], x).findings
    assert lvl.variant == "above"
    waiting = run([{"id": "ry", "type": "macro_threshold", "series": "RY", "above": 2}])
    assert waiting.statuses[0].reason == "No data for RY yet."


def test_a_hedge_that_starts_moving_with_equities_is_flagged() -> None:
    days = [TODAY - timedelta(days=60 - i) for i in range(60)]
    up = [(d, D("0.01") if i % 2 else D("-0.01")) for i, d in enumerate(days)]
    opposite = [(d, -r) for d, r in up]
    rule = {
        "id": "c",
        "type": "correlation_shift",
        "hedge": "gold",
        "against": ["equity"],
        "above": "0.5",
    }
    (f,) = run([rule], inputs(sleeve_returns={"gold": up, "equity": up})).findings
    assert f.subject == "gold/equity" and f.value == 1
    assert run([rule], inputs(sleeve_returns={"gold": opposite, "equity": up})).findings == []


# --- plans, cash, theses, data -------------------------------------------------------------------


def test_a_contribution_is_announced_days_before() -> None:
    plan = {"amount_eur": 500, "cadence": "monthly", "next_date": "2025-01-17"}
    rule = [{"id": "c", "type": "contribution_due", "days_before": 3}]
    (f,) = run(rule, contribution_plan=plan).findings
    assert "2025-03-17" in f.title  # rolled forward month by month
    assert run(rule).statuses[0].reason == "No contribution plan with an amount and a date."  # Q4
    assert next_contribution(date(2025, 1, 31), "monthly", date(2025, 2, 1)) == date(2025, 2, 28)
    assert next_contribution(date(2025, 11, 10), "quarterly", date(2025, 12, 1)) == date(
        2026, 2, 10
    )


def test_cash_only_counts_when_an_account_tracks_it() -> None:
    rule = [{"id": "cash", "type": "cash_buffer"}]
    limits = {"min_cash_eur": 200}
    assert run(rule, risk_limits=limits).statuses[0].reason == "No account tracks cash."  # Q7
    (f,) = run(rule, inputs(tracked_cash_eur=D(150)), risk_limits=limits).findings
    assert f.variant == "below"
    assert run(rule, inputs(tracked_cash_eur=D(250)), risk_limits=limits).findings == []


def test_a_thesis_review_is_due_on_its_cycle() -> None:
    theses = [{"sleeve": "gold", "why": "Hedge", "review_every_days": 30}]
    rule = [{"id": "r", "type": "thesis_review_due"}]
    (f,) = run(rule, theses=theses).findings
    assert f.subject == "gold" and "Hedge" in f.message
    later = inputs(strategy_since=TODAY - timedelta(days=10))
    assert run(rule, later, theses=theses).findings == []


def exposure(label: str, weight: str, parts: list[Part], other: bool = False) -> Exposure:
    value = D(weight) * 1000
    return Exposure(label.lower(), label, value, D(weight), tuple(parts), other)


def holding(source: str, kind: str, value: int) -> Part:
    return Part(source, 1, kind, D(value), None)  # type: ignore[arg-type]


COMPANIES = [
    exposure(
        "Secret Corp",
        "0.12",
        [holding("Secret Corp", "direct", 50), holding("World ETF", "look_through", 70)],
    ),
    exposure("Small Co", "0.04", [holding("World ETF", "look_through", 40)]),
    exposure("Other holdings of World ETF", "0.30", [holding("World ETF", "other", 300)], True),
]


def test_stale_prices_and_the_concentration_rule_waits_for_what_it_needs() -> None:
    (f,) = run([{"id": "s", "type": "stale_data"}], inputs(stale=["B", "A"])).findings
    assert "A, B" in f.message and f.value == 2
    rule = [{"id": "cc", "type": "concentration_limit"}]
    no_limit = run(rule, inputs(opened_etfs=True))
    assert no_limit.findings == [] and "No limit set" in (no_limit.statuses[0].reason or "")
    no_etf = run(rule, inputs(), risk_limits={"max_single_company_lookthrough_pct": 10})
    assert no_etf.findings == [] and "holdings of at least one" in (no_etf.statuses[0].reason or "")
    off = run([{"id": "s", "type": "stale_data", "enabled": False}], inputs(stale=["A"]))
    assert off.findings == [] and off.statuses[0].reason == "Switched off."


def test_push_texts_never_show_euro_amounts_and_the_anonymous_ones_no_names() -> None:
    """Every rule fires once here; none of their push texts may carry a euro figure (FR-NT-07)."""
    rules = [
        {"id": "d", "type": "drift_band"},
        {"id": "t", "type": "trim_threshold"},
        {"id": "dd", "type": "drawdown", "threshold_pct": 10},
        {"id": "m", "type": "price_move", "pct": 3},
        {"id": "lvl", "type": "price_level", "instrument": "IE00B5BMR087", "above": 100},
        {"id": "ry", "type": "macro_threshold", "series": "RY", "above": 1},
        {"id": "c", "type": "contribution_due"},
        {"id": "cash", "type": "cash_buffer"},
        {"id": "s", "type": "stale_data"},
        {"id": "cc", "type": "concentration_limit", "limit_pct": 10},
    ]
    x = inputs(
        sleeves={"equity": SleeveState(D("0.8"), D(800)), "gold": SleeveState(D("0.2"), D(200))},
        positions=[position("Secret Corp", values=[100, 130, 110])],
        macro={"RY": closes(["2"])},
        tracked_cash_eur=D(10),
        stale=["Secret Corp"],
        exposures={"company": COMPANIES},
        opened_etfs=True,
    )
    found = run(
        rules,
        x,
        contribution_plan={"amount_eur": 750, "cadence": "monthly", "next_date": TODAY.isoformat()},
        risk_limits={"min_cash_eur": 100},
    ).findings
    assert {f.rule_type for f in found} == {r["type"] for r in rules}
    money = re.compile(r"€|EUR|\b750\b|\b10\.00\b|\b100\.00\b")
    for f in found:
        assert not money.search(f.push), f.push
        assert not money.search(f.push_anonymous), f.push_anonymous
        assert "Secret Corp" not in f.push_anonymous and "equity" not in f.push_anonymous


def test_a_company_above_the_limit_fires_with_where_it_comes_from() -> None:
    x = inputs(exposures={"company": COMPANIES, "country": []}, opened_etfs=True)
    rule = [{"id": "cc", "type": "concentration_limit", "severity": "high"}]
    (f,) = run(rule, x, risk_limits={"max_single_company_lookthrough_pct": 10}).findings
    assert f.subject == "company:Secret Corp" and f.severity == "high" and f.value == D(12)
    assert "12.0% of your portfolio (limit 10%)" in f.title
    assert "5.0% held directly, 7.0% in World ETF" in f.message
    # the unopened rest of an ETF is no company, however large; a smaller one stays quiet
    assert run(rule, x, risk_limits={"max_single_company_lookthrough_pct": 2}).findings[
        0
    ].value == D(12)
    assert len(run(rule, x, risk_limits={"max_single_company_lookthrough_pct": 2}).findings) == 2
    assert run(rule, x, risk_limits={"max_single_company_lookthrough_pct": 15}).findings == []
    own = [{"id": "cc", "type": "concentration_limit", "limit_pct": 20}]
    assert run(own, x, risk_limits={"max_single_company_lookthrough_pct": 10}).findings == []


def test_a_country_needs_a_limit_on_the_rule_itself() -> None:
    countries = [exposure("United States", "0.55", [holding("World ETF", "look_through", 550)])]
    x = inputs(exposures={"company": [], "country": countries}, opened_etfs=True)
    risk = {"max_single_company_lookthrough_pct": 10}  # a company limit, not a country one
    rule = [{"id": "cc", "type": "concentration_limit", "dimension": "country"}]
    assert "give the rule a limit_pct" in (run(rule, x, risk_limits=risk).statuses[0].reason or "")
    limited = [{**rule[0], "limit_pct": 50}]
    (f,) = run(limited, x, risk_limits=risk).findings
    assert f.subject == "country:United States" and "One country is above" in f.push_anonymous


# --- dedup and cooldown --------------------------------------------------------------------------

NOW = datetime(2025, 3, 14, 20, tzinfo=UTC)


def test_a_new_condition_fires_and_an_open_one_waits_for_its_cooldown() -> None:
    assert should_fire(None, D(6), 7, None, NOW)
    opened = Open(NOW - timedelta(days=3), D(6))
    assert not should_fire(opened, D(6), 7, None, NOW)
    assert should_fire(Open(NOW - timedelta(days=7), D(6)), D(6), 7, None, NOW)


def test_worsening_by_the_step_fires_early() -> None:
    opened = Open(NOW - timedelta(days=1), D(6))
    assert not should_fire(opened, D("6.9"), 7, D(1), NOW)
    assert should_fire(opened, D(7), 7, D(1), NOW)
    assert not should_fire(opened, D(9), 7, None, NOW)  # no step: only the cooldown counts


@given(st.lists(st.integers(min_value=0, max_value=30 * 24), min_size=1, max_size=40))
def test_a_condition_that_stays_true_fires_once_per_cooldown(hours: list[int]) -> None:
    """Runs at arbitrary hours over a month, always with the same measurement: the fires are
    always at least a cooldown apart (FR-ST-04)."""
    cooldown = 7
    state: Open | None = None
    fired: list[datetime] = []
    for h in sorted(hours):
        now = NOW + timedelta(hours=h)
        if should_fire(state, D(6), cooldown, None, now):
            fired.append(now)
            state = Open(now, D(6))
    assert fired  # the first run always fires
    assert all(b - a >= timedelta(days=cooldown) for a, b in zip(fired, fired[1:], strict=False))
