"""The Monte Carlo projection (FR-PF-12): exact compounding without volatility, ordered bands,
repeatable runs, and what it refuses."""

import math
from decimal import Decimal, localcontext

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from folio.analytics.projection import (
    MAX_PATHS,
    MAX_YEARS,
    Assumptions,
    ProjectionError,
    project,
)

D = Decimal


def assume(**over: object) -> Assumptions:
    base: dict[str, object] = {
        "start_value_eur": D(10000),
        "monthly_contribution_eur": D(0),
        "annual_return_pct": D(5),
        "annual_volatility_pct": D(0),
        "years": 10,
        "paths": 200,
        "seed": 1,
    }
    base.update(over)
    return Assumptions(**base)  # type: ignore[arg-type]


def test_without_volatility_it_is_exact_compounding_at_the_annual_return() -> None:
    result = project(assume())
    last = result.points[-1]
    assert last.month == 120
    exact = D(10000) * D("1.05") ** 10  # 16288.946...
    for value in (last.p10_eur, last.median_eur, last.p90_eur):
        assert abs(value - exact) < D("0.02")
    # after 5 years too, and at a month in between
    five = result.points[60]
    assert abs(five.median_eur - D(10000) * D("1.05") ** 5) < D("0.02")
    assert result.points[0].median_eur == D(10000)


def test_contributions_are_added_at_the_start_of_each_month_and_grow_with_it() -> None:
    a = assume(monthly_contribution_eur=D(250), years=5)
    last = project(a).points[-1]
    with localcontext() as ctx:
        ctx.prec = 40
        g = D("1.05") ** (D(1) / D(12))
        value = D(10000)
        for _ in range(60):
            value = (value + D(250)) * g
    assert abs(last.median_eur - value) < D("0.05")
    assert last.invested_eur == D(10000) + D(250) * 60  # what was simply paid in
    assert last.median_eur > last.invested_eur


def test_zero_return_and_zero_volatility_leaves_exactly_what_was_paid_in() -> None:
    result = project(assume(annual_return_pct=D(0), monthly_contribution_eur=D(100), years=3))
    assert [p.median_eur for p in result.points] == [p.invested_eur for p in result.points]


def test_money_leaves_as_decimal_cents() -> None:
    p = project(assume(annual_volatility_pct=D(15), paths=100)).points[7]
    for value in (p.invested_eur, p.p10_eur, p.median_eur, p.p90_eur):
        assert isinstance(value, Decimal) and value == value.quantize(D("0.01"))


def test_the_same_seed_gives_the_same_chart_and_another_seed_another() -> None:
    a = assume(annual_volatility_pct=D(18), years=3)
    again = project(a)
    assert project(a).points == again.points
    assert project(assume(annual_volatility_pct=D(18), years=3, seed=2)).points != again.points


def test_the_median_follows_the_lognormal_median_within_sampling_error() -> None:
    a = assume(
        start_value_eur=D(1000), annual_return_pct=D(5), annual_volatility_pct=D(20),
        years=1, paths=MAX_PATHS,
    )  # fmt: skip
    median = project(a).points[-1].median_eur
    expected = 1000 * 1.05 * math.exp(-0.2 * 0.2 / 2)  # exp(12 * monthly log mean)
    assert abs(float(median) - expected) < 15


def test_more_volatility_widens_the_band_and_a_longer_horizon_too() -> None:
    def width(vol: int, years: int) -> Decimal:
        end = project(assume(annual_volatility_pct=D(vol), years=years, paths=500)).points[-1]
        return end.p90_eur - end.p10_eur

    assert width(10, 5) < width(20, 5) < width(30, 5)
    assert width(15, 2) < width(15, 10)


@settings(max_examples=25, deadline=None)
@given(
    st.integers(min_value=0, max_value=100000),
    st.integers(min_value=0, max_value=2000),
    st.integers(min_value=-20, max_value=30),
    st.integers(min_value=0, max_value=60),
    st.integers(min_value=1, max_value=4),
)
def test_the_band_is_always_ordered_and_never_negative(
    start: int, contribution: int, ret: int, vol: int, years: int
) -> None:
    result = project(
        assume(
            start_value_eur=D(start),
            monthly_contribution_eur=D(contribution),
            annual_return_pct=D(ret),
            annual_volatility_pct=D(vol),
            years=years,
            paths=60,
        )
    )
    assert len(result.points) == years * 12 + 1
    for p in result.points:
        assert 0 <= p.p10_eur <= p.median_eur <= p.p90_eur


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"start_value_eur": D(-1)}, "starting value"),
        ({"monthly_contribution_eur": D(-5)}, "monthly contribution"),
        ({"years": 0}, "1 to 40 years"),
        ({"years": MAX_YEARS + 1}, "1 to 40 years"),
        ({"paths": 0}, "simulated paths"),
        ({"paths": MAX_PATHS + 1}, "simulated paths"),
        ({"annual_return_pct": D(-100)}, "expected return"),
        ({"annual_volatility_pct": D(101)}, "volatility"),
    ],
)
def test_impossible_assumptions_are_refused_in_words(over: dict[str, object], message: str) -> None:
    with pytest.raises(ProjectionError, match=message):
        project(assume(**over))
