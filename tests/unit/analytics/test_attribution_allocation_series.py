from datetime import date
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from folio.analytics.allocation import allocate, drift
from folio.analytics.attribution import PositionPeriod, attribute, dietz_capital
from folio.analytics.series import BridgeStep, bridge, by_month, monthly_returns, rebase

D = Decimal


# --- attribution --------------------------------------------------------------------------------


def test_contributions_in_euro_and_points_for_a_worked_period() -> None:
    start, end = date(2024, 1, 1), date(2024, 1, 21)  # 20 days
    items = [
        PositionPeriod(1, D("1000"), D("1100"), D("0"), income=D("10")),  # +110
        PositionPeriod(2, D("500"), D("700"), D("100")),  # bought 100 on the 11th: +100
    ]
    result = attribute(items, start, end, [(date(2024, 1, 11), D("100"))])
    assert [c.pnl_eur for c in result.contributions] == [D("110"), D("100")]
    assert result.total_pnl_eur == D("210")
    # a flow on the 11th counts for 11 of 20 days: 1500 + 100 * 11/20 = 1555
    assert result.capital == D("1555")
    assert result.total_return == D("210") / D("1555")
    assert result.contributions[0].points == D("110") / D("1555")


def test_a_flow_on_the_first_day_counts_for_the_whole_period() -> None:
    capital = dietz_capital(
        date(2024, 1, 1), date(2024, 1, 11), D("0"), [(date(2024, 1, 2), D("100"))]
    )
    assert capital == D("100")  # invested from the start of the 2nd to the end: 10 of 10 days
    assert dietz_capital(date(2024, 1, 1), date(2024, 1, 1), D("50"), []) == D("50")
    # flows outside the period are ignored
    assert dietz_capital(
        date(2024, 1, 1), date(2024, 1, 11), D("5"), [(date(2023, 1, 1), D("9"))]
    ) == D("5")


def test_no_capital_means_no_percentage() -> None:
    result = attribute(
        [PositionPeriod("x", D("0"), D("0"), D("0"))], date(2024, 1, 1), date(2024, 1, 2), []
    )
    assert result.total_return is None
    assert result.contributions[0].points is None


@settings(max_examples=50, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.decimals(min_value=D("0"), max_value=D("10000"), places=2),
            st.decimals(min_value=D("0"), max_value=D("10000"), places=2),
            st.decimals(min_value=D("0"), max_value=D("2000"), places=2),
            st.decimals(min_value=D("0"), max_value=D("100"), places=2),
        ),
        min_size=1,
        max_size=8,
    )
)
def test_contributions_sum_exactly_to_the_total(
    rows: list[tuple[Decimal, Decimal, Decimal, Decimal]],
) -> None:
    items = [PositionPeriod(i, a, b, f, inc) for i, (a, b, f, inc) in enumerate(rows)]
    flows = [(date(2024, 1, 10), sum((i.flows for i in items), D(0)))]
    result = attribute(items, date(2024, 1, 1), date(2024, 2, 1), flows)
    assert sum((c.pnl_eur for c in result.contributions), D(0)) == result.total_pnl_eur
    if result.total_return is not None:
        points = sum((c.points or D(0) for c in result.contributions), D(0))
        assert abs(points - result.total_return) < D("1E-20")


# --- allocation and drift -----------------------------------------------------------------------


def test_drift_overweight_underweight_and_band() -> None:
    over = drift(D("0.30"), D("0.25"), D("0.03"))
    assert over is not None
    assert (over.pp, over.relative, over.outside_band) == (D("0.05"), D("0.2"), True)
    under = drift(D("0.20"), D("0.25"), D("0.10"))
    assert under is not None
    assert (under.pp, under.relative, under.outside_band) == (D("-0.05"), D("-0.2"), False)
    assert drift(D("0.2"), None) is None
    assert drift(D("0.2"), D("0")) is not None and drift(D("0.2"), D("0")).relative is None  # type: ignore[union-attr]
    nobands = drift(D("0.2"), D("0.25"))
    assert nobands is not None and nobands.outside_band is None


def test_allocation_groups_weighs_and_adds_empty_targets() -> None:
    holdings = [("ETF", D("600")), ("Equity", D("300")), ("ETF", D("100"))]
    result = allocate(holdings, {"ETF": (D("0.5"), D("0.05")), "Gold": (D("0.1"), None)})
    assert result.total_eur == D("1000")
    assert [s.key for s in result.slices] == ["ETF", "Equity", "Gold"]
    etf, equity, gold = result.slices
    assert (etf.value_eur, etf.weight) == (D("700"), D("0.7"))
    assert etf.drift is not None and etf.drift.pp == D("0.2") and etf.drift.outside_band is True
    assert equity.drift is None
    assert gold.weight == 0 and gold.drift is not None and gold.drift.pp == D("-0.1")


def test_an_empty_portfolio_allocates_to_nothing() -> None:
    result = allocate([])
    assert result.total_eur == 0 and result.slices == []


# --- series -------------------------------------------------------------------------------------


def test_rebase_to_a_start_date_even_between_points() -> None:
    series = [(date(2024, 1, d), D(v)) for d, v in [(1, "50"), (3, "55"), (5, "60")]]
    expected = D("60") / D("55") * 100
    on_a_point = rebase(series, date(2024, 1, 3))
    assert on_a_point[0] == (date(2024, 1, 3), D("100"))
    assert abs(on_a_point[1][1] - expected) < D("1E-20")
    # a start between points uses the last value before it
    between = rebase(series, date(2024, 1, 4))
    assert between[0][0] == date(2024, 1, 5) and abs(between[0][1] - expected) < D("1E-20")
    assert rebase(series, date(2023, 1, 1))[0] == (date(2024, 1, 1), D("100"))  # before the data
    assert rebase([], date(2024, 1, 1)) == []
    assert rebase([(date(2024, 1, 1), D("0"))], date(2024, 1, 1)) == []


def test_monthly_returns_from_an_index() -> None:
    index = [
        (date(2024, 1, 1), D("1")),
        (date(2024, 1, 31), D("1.1")),
        (date(2024, 2, 29), D("1.21")),
        (date(2024, 3, 31), D("1.089")),
    ]
    result = monthly_returns(index)
    assert result[(2024, 1)] == D("0.1")
    assert result[(2024, 2)] == D("0.1")
    assert abs(result[(2024, 3)] - D("-0.1")) < D("1E-30")
    assert monthly_returns(index[:1]) == {}


def test_income_by_month() -> None:
    items = [(date(2024, 1, 5), D("10")), (date(2024, 1, 20), D("5")), (date(2024, 3, 1), D("7"))]
    assert by_month(items) == {(2024, 1): D("15"), (2024, 3): D("7")}


def test_the_bridge_ends_where_the_portfolio_ends() -> None:
    positions = [("A", D("1000"), D("1100"), D("0")), ("B", D("500"), D("700"), D("100"))]
    steps = bridge(D("1500"), positions)
    assert steps[0] == BridgeStep("start", D("1500"), "total")
    assert steps[1] == BridgeStep("contributions", D("100"), "delta")
    assert [s.amount_eur for s in steps[2:4]] == [D("100"), D("100")]
    assert steps[-1] == BridgeStep("end", D("1800"), "total")  # 1100 + 700
