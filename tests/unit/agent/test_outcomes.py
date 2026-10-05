"""Outcome tracking arithmetic (FR-AG-06): returns, verdicts, which horizons are due, and the
track record's counts."""

from datetime import date
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from folio.agent import outcomes as o

D = Decimal


def test_a_return_is_the_exact_change_over_the_start_price() -> None:
    assert o.price_return(D("160"), D("170")) == D("0.062500")
    assert o.price_return(D("200"), D("150")) == D("-0.250000")
    assert o.price_return(D("0"), D("5")) is None  # nothing to compare with


def test_only_contributions_and_trims_have_a_direction() -> None:
    up, down = D("0.02"), D("-0.02")
    assert o.verdict("direct_contribution", up) is True
    assert o.verdict("direct_contribution", D("0")) is True  # not lower than where it was
    assert o.verdict("direct_contribution", down) is False
    assert o.verdict("trim", down) is True
    assert o.verdict("trim", up) is False
    for unscored in ("hold", "watch", "review_thesis", "hedge_check", "rebalance", "info"):
        assert o.verdict(unscored, up) is None and o.verdict(unscored, down) is None
    assert o.verdict("trim", None) is None


def test_horizons_are_due_once_their_day_has_come_and_only_once() -> None:
    created = date(2026, 1, 1)
    assert o.pending(created, date(2026, 1, 7), {}) == []  # day 6
    assert o.pending(created, date(2026, 1, 8), {}) == [7]
    assert o.pending(created, date(2026, 2, 1), {}) == [7, 30]
    assert o.pending(created, date(2026, 4, 2), {"d7": {}}) == [30, 90]
    assert o.pending(created, date(2026, 4, 2), {"d7": {}, "d30": {}, "d90": {}}) == []


def test_several_subjects_are_averaged_and_missing_prices_are_left_out() -> None:
    out = o.measure(
        "direct_contribution",
        {"A": D("100"), "B": D("200"), "C": D("50")},
        {"A": D("110"), "B": D("190"), "C": None},
        date(2026, 2, 1),
    )
    assert out["subjects"] == {
        "A": {"start": "100", "end": "110", "return": "0.100000"},
        "B": {"start": "200", "end": "190", "return": "-0.050000"},
    }
    assert out["return"] == "0.025000" and out["hit"] is True  # mean +2.5 %
    assert out["measured_on"] == "2026-02-01" and "note" not in out


def test_nothing_to_compare_is_said_so_and_never_a_miss() -> None:
    out = o.measure("trim", {"A": D("100")}, {"A": None}, date(2026, 2, 1))
    assert out["return"] is None and out["hit"] is None and out["note"] == "no price"


def row(action: str, status: str, **horizons: tuple[str, bool | None]) -> o.Row:
    return o.Row(
        action,
        status,
        {k: {"return": v[0], "hit": v[1]} for k, v in horizons.items()},
    )


def test_the_track_record_counts_by_action_type_and_by_decision() -> None:
    rows = [
        row("direct_contribution", "accepted", d30=("0.05", True)),
        row("direct_contribution", "rejected", d30=("-0.02", False)),
        row("direct_contribution", "new"),  # too young to measure
        row("trim", "accepted", d30=("-0.04", True)),
        row("watch", "seen", d30=("0.10", None)),
    ]
    record = o.summarise(rows)
    by = {a.action_type: a for a in record.actions}
    assert record.total == 5
    contribution = next(h for h in by["direct_contribution"].by_horizon if h.days == 30)
    assert (contribution.measured, contribution.scored, contribution.hits) == (2, 2, 1)
    assert contribution.hit_rate == D("0.5") and contribution.avg_return == D("0.015")
    assert by["direct_contribution"].count == 3 and by["direct_contribution"].scored_type
    watch = next(h for h in by["watch"].by_horizon if h.days == 30)
    assert (watch.measured, watch.scored, watch.hits, watch.hit_rate) == (1, 0, 0, None)
    assert not by["watch"].scored_type  # measured, never counted as a hit
    decisions = {d.decision: d for d in record.decisions}
    assert decisions["accepted"].count == 2 and decisions["accepted"].stats.hit_rate == D("1")
    assert decisions["rejected"].stats.hits == 0 and decisions["rejected"].stats.scored == 1
    assert decisions["undecided"].count == 2  # one new, one seen


@given(
    st.lists(
        st.tuples(
            st.sampled_from(["direct_contribution", "trim", "watch", "hold", "rebalance"]),
            st.sampled_from(["new", "seen", "accepted", "rejected", "snoozed", "expired"]),
            st.one_of(
                st.none(),
                st.decimals(min_value=D("-0.9"), max_value=D("2"), places=4),
            ),
        ),
        max_size=40,
    )
)
def test_counts_always_nest_and_hit_rates_stay_between_zero_and_one(
    items: list[tuple[str, str, Decimal | None]],
) -> None:
    rows = []
    for action, status, change in items:
        outcome = (
            {}
            if change is None
            else {"d30": {"return": str(change), "hit": o.verdict(action, change)}}
        )
        rows.append(o.Row(action, status, outcome))
    record = o.summarise(rows)
    assert sum(a.count for a in record.actions) == record.total == len(rows)
    assert sum(d.count for d in record.decisions) == len(rows)
    for action in record.actions:
        for h in action.by_horizon:
            assert 0 <= h.hits <= h.scored <= h.measured <= action.count
            assert h.hit_rate is None or Decimal(0) <= h.hit_rate <= Decimal(1)
            if not action.scored_type:
                assert h.scored == 0
