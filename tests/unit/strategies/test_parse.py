"""The strategy YAML: validation with line numbers, exact decimals, round trips (FR-ST-01)."""

from decimal import Decimal

import pytest

from folio.agent.schema import RECOMMENDATION_SCHEMA
from folio.strategies.agent_context import principles_and_theses
from folio.strategies.diff import side_by_side
from folio.strategies.parse import StrategyError, parse, to_yaml
from folio.strategies.starter import starter_yaml

GOOD = """\
strategy:
  name: Core long-term
  principles:
    - Rebalance by directing new contributions to underweight sleeves first.
    - "No emotional profit-taking: trims only at pre-committed thresholds."
  macro_series:
    US_REAL_YIELD_10Y: { source: fred, code: DFII10 }
  sleeves:
    - { id: us_equity, members: [IE00B5BMR087], target_pct: 40.5, soft_band_pp: 3, hard_band_pp: 6 }
    - { id: gold_hedge, members: [IE00B4ND3602], target_pct: null, watch: [US_REAL_YIELD_10Y] }
  rules:
    - { id: drift, type: drift_band, applies_to: all, severity: medium, cooldown_days: 7 }
    - { id: real_yield, type: macro_threshold, series: US_REAL_YIELD_10Y, change_bp: 50, applies_to: [gold_hedge] }
  theses:
    - { sleeve: gold_hedge, why: "Non-correlated hedge", review_every_days: 90 }
"""


def lines_of(exc: pytest.ExceptionInfo[StrategyError]) -> list[int | None]:
    return [p.line for p in exc.value.problems]


def test_a_complete_strategy_reads_with_exact_decimals() -> None:
    s = parse(GOOD)
    us = s.sleeve("us_equity")
    assert us is not None and us.target_pct == Decimal("40.5")  # not 40.49999...
    assert s.sleeve("gold_hedge").target_pct is None  # type: ignore[union-attr]  # Q3: empty is fine
    assert [r.type for r in s.rules] == ["drift_band", "macro_threshold"]


def test_a_yaml_syntax_error_names_its_line() -> None:
    broken = GOOD.replace("  rules:\n", "  rules:\n    - { id: oops, type: drift_band\n", 1)
    with pytest.raises(StrategyError) as exc:
        parse(broken)
    assert exc.value.problems[0].message.startswith("YAML syntax")
    assert lines_of(exc)[0] in (13, 14)  # the unclosed flow mapping, or where it is noticed


def test_a_bad_value_names_its_line_and_path() -> None:
    with pytest.raises(StrategyError) as exc:
        parse(GOOD.replace("target_pct: 40.5", "target_pct: 140"))
    (problem,) = exc.value.problems
    assert problem.line == 9 and problem.path == "strategy.sleeves[0].target_pct"
    assert "less than or equal to 100" in problem.message
    assert str(exc.value).startswith("line 9:")


def test_an_unknown_rule_type_names_the_rule_line() -> None:
    with pytest.raises(StrategyError) as exc:
        parse(GOOD.replace("type: drift_band", "type: drift_bands"))
    assert lines_of(exc) == [12]
    assert "drift_band" in exc.value.problems[0].message  # lists what is allowed


def test_a_missing_field_points_at_the_item_that_lacks_it() -> None:
    text = GOOD.replace(
        "  theses:", "    - { id: dd, type: drawdown, severity: high }\n  theses:", 1
    )
    with pytest.raises(StrategyError) as exc:
        parse(text)
    assert lines_of(exc) == [14] and exc.value.problems[0].path.endswith("threshold_pct")


def test_references_must_exist() -> None:
    with pytest.raises(StrategyError, match="not defined"):
        parse(GOOD.replace("applies_to: [gold_hedge]", "applies_to: [silver]"))
    with pytest.raises(StrategyError, match="not under macro_series"):
        parse(GOOD.replace("series: US_REAL_YIELD_10Y", "series: VIX"))
    with pytest.raises(StrategyError, match="used twice"):
        parse(GOOD.replace("id: gold_hedge,", "id: us_equity,"))
    with pytest.raises(StrategyError, match="hard_band_pp must be at least"):
        parse(GOOD.replace("hard_band_pp: 6", "hard_band_pp: 2"))


def test_unknown_keys_and_wrong_shapes_are_refused() -> None:
    with pytest.raises(StrategyError, match="Extra inputs"):
        parse(GOOD.replace("  principles:", "  princples: []\n  principles:", 1))
    with pytest.raises(StrategyError, match="start with `strategy:`"):
        parse("- just a list")
    with pytest.raises(StrategyError, match="not a usable number"):
        parse(GOOD.replace("target_pct: 40.5", "target_pct: .nan"))


def test_the_canonical_yaml_reads_back_to_the_same_strategy() -> None:
    s = parse(GOOD)
    assert parse(to_yaml(s)) == s
    assert "target_pct: 40.5" in to_yaml(s)  # decimals written as plain numbers


def test_the_starter_is_valid_with_every_target_empty() -> None:
    s = parse(starter_yaml("Mine", [("us_equity", ["IE00B5BMR087"]), ('odd "name"', [])]))
    assert [x.id for x in s.sleeves] == ["us_equity", 'odd "name"']
    assert all(x.target_pct is None for x in s.sleeves)
    assert parse(starter_yaml("Empty", [])).sleeves[0].id == "core"


def test_principles_and_theses_reach_the_agent_word_for_word() -> None:
    s = parse(GOOD)
    out = principles_and_theses(s)
    assert out["principles"] == [
        "Rebalance by directing new contributions to underweight sleeves first.",
        "No emotional profit-taking: trims only at pre-committed thresholds.",
    ]
    assert out["theses"][0]["why"] == "Non-correlated hedge"


def test_the_recommendation_schema_is_strict_and_asks_about_principles() -> None:
    rec = RECOMMENDATION_SCHEMA["$defs"]["rec"]
    assert "departs_from_principles" in rec["required"]
    assert rec["properties"]["departs_from_principles"]["type"] == ["string", "null"]

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
            for bad in ("minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems"):
                assert bad not in node  # structured outputs do not support bounds
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(RECOMMENDATION_SCHEMA)


def test_a_diff_pairs_changed_lines_side_by_side() -> None:
    rows = side_by_side("a\nb\nc\n", "a\nB\nc\nd\n")
    assert [(r.kind, r.old_line, r.new_line) for r in rows] == [
        ("same", 1, 1),
        ("changed", 2, 2),
        ("same", 3, 3),
        ("added", None, 4),
    ]
    assert [r.kind for r in side_by_side("x\ny\n", "x\n")] == ["same", "removed"]
