from datetime import date, timedelta
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from folio.analytics.risk import (
    beta,
    correlation,
    correlation_matrix,
    daily_returns,
    drawdown,
    risk_figures,
    sharpe,
    volatility,
)

D = Decimal
DAY0 = date(2024, 1, 1)


def series(values: list[str]) -> list[tuple[date, Decimal]]:
    return [(DAY0 + timedelta(days=i), D(v)) for i, v in enumerate(values)]


def test_daily_returns_from_an_index_and_only_for_trading_days() -> None:
    index = series(["1", "1.1", "1.1", "1.21"])
    assert [r for _, r in daily_returns(index)] == [D("0.1"), D(0), D("0.1")]
    trading = {DAY0 + timedelta(days=1), DAY0 + timedelta(days=3)}
    assert [d for d, _ in daily_returns(index, trading)] == sorted(trading)


def test_volatility_of_a_hand_worked_sample() -> None:
    # mean 0.02, squared deviations sum to 0.001, sample variance 0.00025, daily sd 0.01581...
    returns = series(["0.01", "0.03", "0.02", "0.04", "0.00"])
    result = volatility(returns)
    assert result is not None
    assert abs(result - D("0.063").sqrt()) < D("1E-25")  # sqrt(0.00025 * 252)


def test_volatility_needs_enough_days_and_is_zero_when_flat() -> None:
    assert volatility(series(["0.01", "0.02"])) is None
    flat = volatility(series(["0.01"] * 6))
    assert flat == 0


def test_drawdown_depth_dates_and_current() -> None:
    result = drawdown(series(["1", "1.2", "0.9", "1.5", "1.2"]))
    assert [v for _, v in result.series] == [D(0), D(0), D("-0.25"), D(0), D("-0.2")]
    assert result.maximum == D("-0.25")
    assert result.maximum_start == DAY0 + timedelta(days=1)  # the peak of 1.2
    assert result.maximum_end == DAY0 + timedelta(days=2)
    assert result.current == D("-0.2")


def test_drawdown_of_a_rising_or_empty_series() -> None:
    rising = drawdown(series(["1", "1.1", "1.2"]))
    assert rising.maximum == 0 and rising.current == 0 and rising.maximum_start is None
    empty = drawdown([])
    assert empty.maximum == 0 and empty.current == 0 and empty.series == []


def test_sharpe() -> None:
    assert sharpe(D("0.08"), D("0.02"), D("0.12")) == D("0.5")
    assert sharpe(None, D("0.02"), D("0.12")) is None
    assert sharpe(D("0.08"), D("0.02"), D("0")) is None
    assert sharpe(D("0.08"), D("0.02"), None) is None


def test_beta_of_a_position_that_moves_twice_as_much() -> None:
    bench = series(["0.01", "-0.02", "0.015", "0.005", "-0.01", "0.02"])
    double = [(d, v * 2) for d, v in bench]
    result = beta(double, bench)
    assert result is not None and abs(result - 2) < D("1E-30")
    assert beta(double[:3], bench[:3]) is None  # too little overlap
    assert beta(double, series(["0.01"] * 6)) is None  # a benchmark that never moves


def test_correlation_of_opposite_and_scaled_series() -> None:
    a = series(["0.01", "-0.02", "0.015", "0.005", "-0.01", "0.02"])
    opposite = [(d, -v) for d, v in a]
    scaled = [(d, v * 3 + D("0.001")) for d, v in a]
    assert correlation(a, opposite) == -1
    scaled_result = correlation(a, scaled)
    assert scaled_result is not None and abs(scaled_result - 1) < D("1E-30")
    assert correlation(a, series(["0.01"] * 6)) is None
    assert correlation(a, a[:3]) is None


def test_gold_against_equities_is_visible_in_the_matrix() -> None:
    equities = series(["0.010", "-0.020", "0.015", "0.005", "-0.010", "0.020", "-0.012"])
    gold = series(["-0.002", "0.006", "-0.004", "-0.001", "0.003", "-0.005", "0.004"])
    matrix = correlation_matrix({1: equities, 2: gold})
    assert matrix[1][1] == 1 and matrix[2][2] == 1
    assert matrix[1][2] == matrix[2][1]
    value = matrix[1][2]
    assert value is not None and value < D("-0.9")


def test_risk_figures_bundle() -> None:
    index = series(["1", "1.01", "1.0302", "1.0199", "1.05", "1.0395", "1.06", "1.07"])
    figures = risk_figures(index, None, D("0.02"), benchmark_returns=daily_returns(index))
    assert figures.volatility is not None and figures.volatility > 0
    assert figures.max_drawdown < 0
    assert figures.beta is not None and abs(figures.beta - 1) < D("1E-30")
    assert figures.sharpe is not None and figures.annual_return is not None
    assert figures.current_drawdown == 0  # the last point is a new peak


@settings(max_examples=40, deadline=None)
@given(
    st.lists(
        st.lists(
            st.decimals(min_value=D("-0.05"), max_value=D("0.05"), places=4), min_size=8, max_size=8
        ),
        min_size=2,
        max_size=5,
    )
)
def test_correlation_matrix_is_symmetric_with_unit_diagonal_in_range(
    rows: list[list[Decimal]],
) -> None:
    matrix = correlation_matrix({i: series([str(v) for v in row]) for i, row in enumerate(rows)})
    for a in matrix:
        assert matrix[a][a] == 1
        for b in matrix:
            value = matrix[a][b]
            assert value == matrix[b][a]
            if value is not None:
                assert D(-1) <= value <= D(1)
