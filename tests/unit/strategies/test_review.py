"""The quarterly review's arithmetic (FR-ST-08): drift at month ends and on the worst day, signal
counts, and the summary text. Pure; no database."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from folio.agent.outcomes import Row
from folio.strategies.review import Quarter, SignalIn, SleeveIn, build_review, render

D = Decimal
Q3 = Quarter(2026, 3)


def weights(per_day: dict[date, dict[str, str]]) -> dict[date, dict[str, Decimal]]:
    return {d: {k: D(v) for k, v in w.items()} for d, w in per_day.items()}


def a_quarter() -> dict[date, dict[str, Decimal]]:
    """Every day of Q3 2026: gold starts on target (40 %), falls to 31 % at the end of August, and
    is back to 38 % at the end of September."""
    out: dict[date, dict[str, str]] = {}
    day = Q3.start
    while day <= Q3.end:
        gold = "0.40" if day < date(2026, 8, 20) else "0.31" if day <= date(2026, 8, 31) else "0.38"
        if day == date(2026, 9, 30):
            gold = "0.38"
        out[day] = {"gold": gold, "equity": str(D(1) - D(gold))}
        day += timedelta(days=1)
    return weights(out)


def test_a_quarter_knows_its_dates_and_its_neighbours() -> None:
    assert (Q3.label, Q3.start, Q3.end) == ("2026Q3", date(2026, 7, 1), date(2026, 9, 30))
    assert Quarter.parse("2026q1").end == date(2026, 3, 31)
    assert Quarter.of(date(2026, 10, 5)) == Quarter(2026, 4)
    assert Quarter(2026, 1).previous() == Quarter(2025, 4)
    assert Quarter(2026, 4).previous() == Q3
    with pytest.raises(ValueError, match="like 2026Q3"):
        Quarter.parse("Q5")


def test_drift_is_read_at_each_month_end_and_on_the_worst_day() -> None:
    sleeves = [
        SleeveIn("gold", D("40"), D("5"), D("8")),
        SleeveIn("equity", D("60"), None, None),
    ]
    review = build_review(Q3, "My strategy", sleeves, a_quarter(), [], [])
    gold = review.sleeves[0]
    assert [(p.day, p.drift_pp) for p in gold.month_ends] == [
        (date(2026, 7, 31), D("0.00")),
        (date(2026, 8, 31), D("-9.00")),
        (date(2026, 9, 30), D("-2.00")),
    ]
    assert gold.worst is not None and gold.worst.drift_pp == D("-9.00")
    assert gold.worst.day == date(2026, 8, 31)  # the latest of the equally bad days
    assert gold.days_outside_hard == 12  # 20 to 31 August: more than 8 pp from the target
    assert gold.days_outside_soft == 0
    equity = review.sleeves[1]
    assert equity.worst is not None and equity.worst.drift_pp == D("9.00")
    assert equity.days_outside_hard == 0  # no band set: never counted
    assert review.days_with_data == 92 and review.notes == []


def test_a_sleeve_without_a_target_is_said_to_be_unjudged() -> None:
    review = build_review(Q3, "S", [SleeveIn("gold", None, None, None)], a_quarter(), [], [])
    assert review.sleeves[0].worst is None
    assert review.notes == ["gold has no target yet, so its drift cannot be judged."]
    assert "- gold: no target set." in render(review)


def test_a_quarter_with_no_history_says_so() -> None:
    review = build_review(Q3, "S", [SleeveIn("gold", D("40"), None, None)], {}, [], [])
    assert review.days_with_data == 0 and review.sleeves[0].month_ends == []
    assert "There is no portfolio history in this quarter." in review.notes


def test_signals_are_counted_per_rule_with_their_worst_severity() -> None:
    signals = [
        SignalIn("drift", "medium", date(2026, 8, 20)),
        SignalIn("drift", "high", date(2026, 8, 21)),
        SignalIn("drift", "low", date(2026, 9, 1)),
        SignalIn("real_yield", "low", date(2026, 9, 3)),
    ]
    review = build_review(Q3, "S", [], a_quarter(), signals, [])
    assert [(s.rule_id, s.count, s.worst_severity) for s in review.signals] == [
        ("drift", 3, "high"),
        ("real_yield", 1, "low"),
    ]


def test_the_agents_advice_is_summarised_by_decision_and_outcome() -> None:
    rows = [
        Row("direct_contribution", "accepted", {"d30": {"return": "0.03", "hit": True}}),
        Row("direct_contribution", "rejected", {"d30": {"return": "-0.01", "hit": False}}),
        Row("watch", "expired", {}),
    ]
    review = build_review(Q3, "S", [], a_quarter(), [], rows)
    assert review.recommendations.made == 3
    assert review.recommendations.by_status == {"accepted": 1, "rejected": 1, "expired": 1}
    text = render(review)
    assert "The agent made 3 recommendation(s): 1 accepted, 1 expired, 1 rejected." in text
    assert "direct_contribution: 1 of 2 would have been right after 30 days (price only)." in text


def test_the_text_leads_with_the_quarter_and_the_sleeves() -> None:
    sleeves = [SleeveIn("gold", D("40"), D("5"), D("8"))]
    signals = [SignalIn("drift", "high", date(2026, 8, 21))]
    text = render(build_review(Q3, "My strategy", sleeves, a_quarter(), signals, []))
    lines = text.splitlines()
    assert lines[0] == "Quarterly review of My strategy, 2026Q3 (2026-07-01 to 2026-09-30)."
    assert (
        "- gold (target 40%): month ends Jul +0.0 pp, Aug -9.0 pp, Sep -2.0 pp; "
        "furthest -9.0 pp on 2026-08-31; 12 day(s) outside the hard band, "
        "0 outside the soft band." in lines
    )
    assert "Signals that fired: drift 1x (worst high)." in lines
    assert "The agent made no recommendations." in lines
