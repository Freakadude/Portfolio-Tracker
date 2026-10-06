"""Backtesting a rule over history (FR-ST-06): which days it would have fired, with what value, and
the same repeat filter as live signals. Pure: the history is built by hand."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest

from folio.strategies.backtest import (
    NOT_BACKTESTABLE,
    BacktestError,
    History,
    Meta,
    run_backtest,
)
from folio.strategies.schema import StrategyDef

D = Decimal
START = date(2026, 1, 1)
GOLD, EQUITY = 1, 2


def strategy(*rules: dict[str, Any]) -> StrategyDef:
    return StrategyDef.model_validate(
        {
            "name": "Test",
            "macro_series": {"RY": {"source": "fred", "code": "DFII10"}},
            "sleeves": [
                {"id": "equity", "target_pct": 60, "soft_band_pp": 5, "hard_band_pp": 8},
                {"id": "gold", "target_pct": 40, "soft_band_pp": 5, "hard_band_pp": 8},
            ],
            "rules": list(rules),
        }
    )


def history(gold_pct: list[int], **over: Any) -> History:
    """One day per entry of `gold_pct`: gold is that share of a 1000 euro portfolio."""
    days = [START + timedelta(days=i) for i in range(len(gold_pct))]
    values = [{GOLD: D(g * 10), EQUITY: D((100 - g) * 10)} for g in gold_pct]
    base: dict[str, Any] = {
        "days": days,
        "values": values,
        "eur_closes": {},
        "native_dates": {},
        "native_closes": {},
        "meta": {GOLD: Meta("Gold ETC", "IE00B4ND3602", "EUR"), EQUITY: Meta("World", None, "EUR")},
        "sleeve_of": {GOLD: "gold", EQUITY: "equity"},
        "index": [],
        "sleeve_returns": {},
        "macro": {},
        "trading_days": frozenset(days),
        "cash": [None] * len(days),
    }
    base.update(over)
    return History(**base)


DRIFT = {"id": "drift", "type": "drift_band", "cooldown_days": 7}
#          days 1-9 on target          10-20 at 30 % (-10 pp)       21-30 back to 38 %
PATH = [40] * 9 + [30] * 11 + [38] * 10


def test_a_drift_rule_lists_the_days_it_would_have_fired_with_the_drift() -> None:
    result = run_backtest(strategy(DRIFT), history(PATH), START, START + timedelta(days=29))
    assert result.days_checked == 30
    fired = [(f.day, f.subject, f.severity, f.value) for f in result.firings]
    # gold is 10 pp under on 10 January (a hard breach, so high) and, still true after the
    # 7-day cooldown, again on 17 January; equity is 10 pp over on the same days
    assert (date(2026, 1, 10), "gold", "high", D(10)) in fired
    assert (date(2026, 1, 17), "gold", "high", D(10)) in fired
    assert (date(2026, 1, 10), "equity", "high", D(10)) in fired
    assert len(result.firings) == 4  # two sleeves, two firings each
    assert all(f.rule_id == "drift" and f.rule_type == "drift_band" for f in result.firings)
    assert "10.0 pp" in result.firings[0].message
    (report,) = result.rules
    assert (report.backtestable, report.days_true, report.fired, report.reason) == (
        True,
        22,
        4,
        None,
    )


def test_a_condition_that_clears_fires_again_at_once_when_it_returns() -> None:
    out_back_out = [40] * 3 + [30] * 2 + [40] * 3 + [30] * 2  # out, back inside, out again
    result = run_backtest(
        strategy(DRIFT), history(out_back_out), START, START + timedelta(days=len(out_back_out) - 1)
    )
    gold = [f.day for f in result.firings if f.subject == "gold"]
    assert gold == [date(2026, 1, 4), date(2026, 1, 9)]  # not held back by the 7-day cooldown


def test_a_condition_that_worsens_fires_again_before_the_cooldown() -> None:
    rule = {**DRIFT, "worsen_step": 3, "cooldown_days": 30}
    worsening = [40] * 2 + [30] * 3 + [25] * 3  # -10 pp, then -15 pp
    result = run_backtest(
        strategy(rule), history(worsening), START, START + timedelta(days=len(worsening) - 1)
    )
    gold = [(f.day, f.value) for f in result.firings if f.subject == "gold"]
    assert gold == [(date(2026, 1, 3), D(10)), (date(2026, 1, 6), D(15))]  # +5 pp is over the step


def test_only_the_chosen_rule_and_range_are_tested() -> None:
    other = {"id": "trim", "type": "trim_threshold"}
    s = strategy(DRIFT, other)
    s = StrategyDef.model_validate(
        {
            **s.model_dump(mode="json"),
            "sleeves": [
                {"id": "equity", "target_pct": 60, "soft_band_pp": 5, "trim_threshold_pct": 55},
                {"id": "gold", "target_pct": 40, "soft_band_pp": 5},
            ],
        }
    )
    h = history(PATH)
    only_trim = run_backtest(s, h, START, START + timedelta(days=29), ["trim"])
    assert {f.rule_id for f in only_trim.firings} == {"trim"}
    assert [r.rule_id for r in only_trim.rules] == ["trim"]
    window = run_backtest(s, h, date(2026, 1, 12), date(2026, 1, 14), ["drift"])
    assert window.days_checked == 3 and {f.day for f in window.firings} == {date(2026, 1, 12)}
    with pytest.raises(BacktestError, match="no rule nope"):
        run_backtest(s, h, START, START, ["nope"])


def test_rules_that_need_what_was_not_kept_are_named_not_guessed() -> None:
    kinds = {
        "stale_data": {"id": "stale", "type": "stale_data"},
        "contribution_due": {"id": "contrib", "type": "contribution_due"},
        "thesis_review_due": {"id": "review", "type": "thesis_review_due"},
    }
    result = run_backtest(
        strategy(DRIFT, *kinds.values()), history(PATH), START, START + timedelta(days=29)
    )
    by_id = {r.rule_id: r for r in result.rules}
    for name, rule in kinds.items():
        report = by_id[rule["id"]]
        assert (report.backtestable, report.fired, report.days_true) == (False, 0, 0)
        assert report.reason == NOT_BACKTESTABLE[name]
    assert by_id["drift"].backtestable and {f.rule_id for f in result.firings} == {"drift"}


def test_a_rule_that_is_waiting_for_numbers_says_what_for() -> None:
    no_targets = StrategyDef.model_validate(
        {
            "name": "T",
            "sleeves": [{"id": "gold"}, {"id": "equity"}],
            "rules": [DRIFT],
        }
    )
    result = run_backtest(no_targets, history(PATH), START, START + timedelta(days=29))
    (report,) = result.rules
    assert report.reason == "No sleeve has a target and a band yet." and result.firings == []


def test_price_rules_use_the_closes_of_each_past_day() -> None:
    days = [START + timedelta(days=i) for i in range(10)]
    closes = [D(100)] * 4 + [D(60)] * 6  # a 40 percent fall on the fifth day
    h = history(
        [40] * 10,
        eur_closes={GOLD: list(closes)},
        native_dates={GOLD: days},
        native_closes={GOLD: list(closes)},
    )
    s = strategy(
        {"id": "dd", "type": "drawdown", "scope": "position", "threshold_pct": 25},
        {"id": "lvl", "type": "price_level", "instrument": "IE00B4ND3602", "below": 80},
    )
    result = run_backtest(s, h, START, days[-1])
    fired = {(f.rule_id, f.day) for f in result.firings}
    assert ("dd", date(2026, 1, 5)) in fired and ("lvl", date(2026, 1, 5)) in fired
    assert not any(f.day < date(2026, 1, 5) for f in result.firings)  # nothing before the fall
    dd = next(f for f in result.firings if f.rule_id == "dd")
    assert dd.subject == "Gold ETC" and dd.value == D(40)


def test_days_without_trading_are_skipped_and_an_empty_range_says_so() -> None:
    days = [START + timedelta(days=i) for i in range(10)]
    h = history([30] * 10, trading_days=frozenset(days[:5]))
    result = run_backtest(strategy(DRIFT), h, START, days[-1])
    assert result.days_checked == 5
    nothing = run_backtest(strategy(DRIFT), h, date(2027, 1, 1), date(2027, 1, 5))
    assert nothing.days_checked == 0 and nothing.notes == [
        "There are no trading days with data in that range."
    ]


def test_days_before_anything_was_held_are_not_judged() -> None:
    h = history([40] * 3)
    h.values[
        0
    ] = {}  # the day before the first purchase: an empty portfolio is not 60 pp off target
    result = run_backtest(strategy(DRIFT), h, START, START + timedelta(days=2))
    assert result.days_checked == 2 and result.firings == []
