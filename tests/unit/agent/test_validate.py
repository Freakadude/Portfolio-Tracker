"""The parts of the code gate that the scenarios do not pin down: number reading, evidence and
calculation rules in isolation (FR-AG-03)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from folio.agent.schema import RECOMMENDATION_SCHEMA
from folio.agent.validate import (
    Calc,
    Facts,
    Past,
    check_output,
    unsupported_numbers,
)

D = Decimal
NOW = datetime(2026, 10, 14, 17, 30, tzinfo=UTC)


def facts(*numbers: str) -> frozenset[Decimal]:
    return frozenset(D(n) for n in numbers)


# --- numbers in text -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "known"),
    [
        ("Buy 3 units", ("3",)),
        ("a weight of 25%", ("0.25",)),  # a weight the tools gave as a fraction
        ("a weight of 25%", ("25",)),  # or already as a percentage
        ("5.0 pp under target", ("0.05",)),
        ("invest EUR 1.234,56 now", ("1234.56",)),  # a European amount
        ("invest EUR 1,234.56 now", ("1234.56",)),
        ("invest €1.234 now", ("1234",)),  # "1.234" read as one thousand two hundred thirty-four
        ("invest €1.234 now", ("1.234",)),  # or as one point two three four
        ("about 12,5% of the fund", ("0.125",)),
        ("a 1 234 EUR order", ("1234",)),  # a space as the thousands separator
        ("sell 2 shares", ("2",)),
    ],
)
def test_figures_that_a_tool_returned_are_accepted_however_they_are_written(
    text: str, known: tuple[str, ...]
) -> None:
    assert unsupported_numbers(text, facts(*known)) == []


@pytest.mark.parametrize(
    ("text", "known"),
    [
        ("Buy 4 units", ("3",)),
        ("a weight of 26%", ("0.25",)),
        ("invest €1.234 now", ("999",)),
        ("5.5 pp under target", ("0.05",)),  # rounding is allowed to the digits shown, not beyond
        ("invest $500", ()),
    ],
)
def test_figures_that_no_tool_returned_are_found(text: str, known: tuple[str, ...]) -> None:
    assert unsupported_numbers(text, facts(*known)) != []


def test_a_figure_is_allowed_to_be_rounded_to_the_digits_shown() -> None:
    assert unsupported_numbers("a weight of 25.1%", facts("0.2513")) == []
    assert unsupported_numbers("a weight of 25%", facts("0.2513")) == []
    assert unsupported_numbers("a weight of 25.5%", facts("0.2513")) != []


def test_bare_numbers_such_as_dates_and_day_counts_are_not_checked() -> None:
    text = "Over the last 14 days, since 2026-10-01, in 3 of the 8 sleeves, at step 2."
    assert unsupported_numbers(text, facts()) == []


# --- evidence and calculations ---------------------------------------------------------------


def rec(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "action_type": "watch",
        "severity": "low",
        "subjects": ["gold_hedge"],
        "title": "Watch it",
        "summary": "A thing.",
        "rationale": "Because.",
        "calculation_id": None,
        "evidence": [{"kind": "metric", "ref": "get_positions", "note": "n"}],
        "sources": [],
        "confidence": "low",
        "departs_from_principles": None,
        "what_would_change_this": "More.",
        "expires_in_days": 7,
    }
    base.update(over)
    return base


def run(*recs: dict[str, object], f: Facts | None = None, past: list[Past] | None = None):  # type: ignore[no-untyped-def]
    seen = f or Facts(tools=frozenset({"get_positions", "run_calculator"}))
    return check_output({"digest": "d", "recommendations": list(recs)}, seen, past or [], NOW)


def test_a_metric_citation_may_name_a_tool_with_a_detail() -> None:
    assert run(
        rec(evidence=[{"kind": "metric", "ref": "get_positions:filter=sleeve", "note": "n"}])
    ).accepted
    assert not run(rec(evidence=[{"kind": "metric", "ref": "get_prices", "note": "n"}])).accepted


def test_a_trade_needs_a_calculation_about_its_subjects() -> None:
    calc = Calc("allocator", frozenset({"us_equity"}), facts("3"))
    f = Facts(tools=frozenset({"get_positions"}), calculations={"c1": calc})
    trade = rec(
        action_type="direct_contribution",
        subjects=["gold_hedge"],
        calculation_id="c1",
        summary="Buy 3 units.",
    )
    refused = run(trade, f=f).verdicts[0]
    assert not refused.accepted and "the calculation is about other subjects" in refused.reasons
    ok = rec(
        action_type="direct_contribution",
        subjects=["us_equity"],
        calculation_id="c1",
        summary="Buy 3 units.",
    )
    assert run(ok, f=f).accepted
    missing = rec(action_type="trim", subjects=["us_equity"], calculation_id=None)
    assert "a trade needs a calculation from this run" in run(missing, f=f).verdicts[0].reasons
    unknown = rec(action_type="trim", subjects=["us_equity"], calculation_id="nope")
    assert "a trade needs a calculation from this run" in run(unknown, f=f).verdicts[0].reasons


def test_a_non_trade_may_not_cite_a_calculation_that_does_not_exist() -> None:
    refused = run(rec(calculation_id="ghost")).verdicts[0]
    assert not refused.accepted and "the calculation it cites does not exist" in refused.reasons


def test_the_calculations_numbers_may_be_quoted() -> None:
    calc = Calc("trim", frozenset({"x"}), facts("2", "0.18"))
    f = Facts(tools=frozenset({"run_calculator"}), calculations={"c": calc})
    text = "Sell 2 units to bring the weight down to 18%."
    trade = rec(action_type="trim", subjects=["x"], calculation_id="c", summary=text,
                evidence=[{"kind": "metric", "ref": "run_calculator", "note": "n"}])  # fmt: skip
    assert run(trade, f=f).accepted


# --- anti-churn -------------------------------------------------------------------------------


def trim() -> dict[str, object]:
    return rec(action_type="trim", subjects=["us_equity"], calculation_id="c", severity="medium",
               summary="Sell 2 units.", evidence=[{"kind": "signal", "ref": "1", "note": "n"}])  # fmt: skip


def churn_facts(signal_time: datetime) -> Facts:
    return Facts(
        signals={"1": signal_time},
        calculations={"c": Calc("trim", frozenset({"us_equity"}), facts("2"))},
    )


def earlier(action: str, days: int, status: str = "accepted") -> Past:
    return Past(frozenset({"us_equity"}), action, NOW - timedelta(days=days), status)


def test_the_opposite_of_a_recent_recommendation_is_refused() -> None:
    f = churn_facts(NOW - timedelta(hours=1))
    assert not run(trim(), f=f, past=[earlier("direct_contribution", 5)]).accepted
    assert run(trim(), f=f, past=[earlier("direct_contribution", 15)]).accepted  # long enough ago
    assert run(trim(), f=f, past=[earlier("trim", 5)]).accepted  # the same direction
    assert run(trim(), f=f, past=[earlier("watch", 5)]).accepted  # not directional
    assert run(trim(), f=f, past=[earlier("direct_contribution", 5, "rejected")]).accepted
    assert run(trim(), f=f, past=[earlier("direct_contribution", 5, "expired")]).accepted
    other = Past(frozenset({"gold_hedge"}), "direct_contribution", NOW - timedelta(days=2), "new")
    assert run(trim(), f=f, past=[other]).accepted  # another subject


def test_the_other_way_round_is_refused_too() -> None:
    contribution = rec(action_type="direct_contribution", subjects=["us_equity"], calculation_id="c",
                       summary="Buy 2 units.", evidence=[{"kind": "signal", "ref": "1", "note": "n"}])  # fmt: skip
    f = churn_facts(NOW - timedelta(hours=1))
    assert not run(contribution, f=f, past=[earlier("trim", 3, "new")]).accepted


def test_a_critical_recommendation_needs_evidence_newer_than_the_earlier_one() -> None:
    critical = {**trim(), "severity": "critical"}
    past = [earlier("direct_contribution", 5)]
    stale = churn_facts(NOW - timedelta(days=6))  # the evidence is older than the contribution
    assert not run(critical, f=stale, past=past).accepted
    fresh = churn_facts(NOW - timedelta(hours=1))
    assert run(critical, f=fresh, past=past).accepted


# --- the whole answer -------------------------------------------------------------------------


def test_an_answer_that_does_not_follow_the_schema_is_a_problem_for_the_run() -> None:
    for bad in (
        None,
        [],
        {"digest": "d"},
        {"digest": "d", "recommendations": "none"},
        {"digest": 1, "recommendations": [], "x": 1},
    ):
        out = check_output(bad, Facts(), [], NOW)
        assert out.problems and out.accepted == []


def test_the_digest_is_kept_and_cut_to_a_sane_length() -> None:
    out = check_output(
        {"digest": "  " + "x" * 5000 + "  ", "recommendations": []}, Facts(), [], NOW
    )
    assert len(out.digest) == 2000


def test_the_pydantic_free_reader_accepts_exactly_the_fields_of_appendix_c() -> None:
    declared = set(RECOMMENDATION_SCHEMA["$defs"]["rec"]["properties"])
    assert declared == set(rec())  # a field added to the schema must be read by the gate
