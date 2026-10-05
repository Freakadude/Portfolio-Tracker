import csv
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from folio.analytics.returns import (
    DailyPoint,
    annualise,
    return_figures,
    twr,
    twr_index,
    xirr,
    xirr_flows,
)

D = Decimal
FIXTURES = Path(__file__).parents[2] / "fixtures" / "analytics"
DAY0 = date(2024, 1, 1)


def point(offset: int, value: str, flow: str = "0", income: str = "0") -> DailyPoint:
    return DailyPoint(DAY0 + timedelta(days=offset), D(value), D(flow), D(income))


def test_twr_links_daily_returns_with_flows_at_the_start_of_the_day() -> None:
    # day 1: 1000 -> 1100 is +10%. Day 2: 1100 comes in first, the 2200 base grows to 2310: +5%.
    series = [point(0, "1000"), point(1, "1100"), point(2, "2310", flow="1100")]
    assert twr(series) == D("0.155")  # 1.10 * 1.05 - 1


def test_a_withdrawal_does_not_look_like_a_loss() -> None:
    # 1000 grows 10% to 1100; then 600 leaves at the start of the next day and the rest is flat
    series = [point(0, "1000"), point(1, "1100"), point(2, "500", flow="-600")]
    assert twr(series) == D("0.1")


def test_income_is_part_of_the_return() -> None:
    series = [point(0, "1000"), point(1, "1000", income="20")]
    assert twr(series) == D("0.02")


def test_the_index_starts_at_one_and_follows_every_day() -> None:
    series = [point(0, "1000"), point(1, "1100"), point(2, "1100")]
    assert twr_index(series) == [
        (DAY0, D(1)),
        (DAY0 + timedelta(days=1), D("1.1")),
        (DAY0 + timedelta(days=2), D("1.1")),
    ]


def test_days_without_capital_or_after_a_full_sale_are_skipped() -> None:
    series = [
        point(0, "0"),  # nothing held yet
        point(1, "1000", flow="1000"),  # bought at the start of the day: flat, no growth known
        point(2, "1100"),
        point(3, "0", flow="-1100"),  # everything sold: no end value to measure
        point(4, "0"),  # nothing held
    ]
    assert twr(series) == D("0.1")


def test_too_short_a_series_has_no_return() -> None:
    assert twr([]) is None
    assert twr([point(0, "100")]) is None
    assert twr_index([]) == []
    assert return_figures([point(0, "100")]) is None


def test_annualising() -> None:
    result = annualise(D("0.21"), 730)  # 21% in two years is 10% a year
    assert result is not None
    assert abs(result - D("0.1")) < D("1E-30")
    assert annualise(D("-1"), 30) is None
    assert annualise(D("0.1"), 0) is None


def test_xirr_for_one_investment() -> None:
    flows = [(date(2023, 1, 1), D("-1000")), (date(2024, 12, 31), D("1210"))]  # 730 days: 2 years
    result = xirr(flows)
    assert result is not None
    assert abs(result - D("0.1")) < D("1E-12")


def test_xirr_for_two_contributions() -> None:
    # -1000 now, -1000 after a year, 2310 after two years: exactly 10% a year
    flows = [
        (date(2023, 1, 1), D("-1000")),
        (date(2024, 1, 1), D("-1000")),
        (date(2024, 12, 31), D("2310")),
    ]
    result = xirr(flows)
    assert result is not None
    assert abs(result - D("0.1")) < D("1E-12")


def test_xirr_can_be_negative() -> None:
    result = xirr([(date(2023, 1, 1), D("-1000")), (date(2024, 1, 1), D("900"))])
    assert result is not None
    assert abs(result - D("-0.1")) < D("1E-12")


def test_xirr_needs_money_both_ways() -> None:
    assert xirr([]) is None
    assert xirr([(DAY0, D("-100"))]) is None
    assert xirr([(DAY0, D("-100")), (DAY0 + timedelta(days=30), D("-50"))]) is None
    assert xirr([(DAY0, D("100")), (DAY0 + timedelta(days=30), D("50"))]) is None


def test_xirr_flows_of_a_series() -> None:
    series = [
        point(0, "1000"),
        point(10, "1600", flow="500", income="5"),
        point(20, "1100", flow="-600"),
    ]
    assert xirr_flows(series) == [
        (DAY0, D("-1000")),
        (DAY0 + timedelta(days=10), D("-495")),  # 500 in, 5 income back
        (DAY0 + timedelta(days=20), D("600")),  # withdrawal
        (DAY0 + timedelta(days=20), D("1100")),  # the end value
    ]
    assert xirr_flows([point(0, "1000")]) == []


def test_reference_spreadsheet_case_matches_to_a_hundredth_of_a_percentage_point() -> None:
    expected = json.loads((FIXTURES / "returns_reference.expected.json").read_text())
    with (FIXTURES / "returns_reference.csv").open() as fh:
        series = [
            DailyPoint(date.fromisoformat(r["date"]), D(r["value"]), D(r["flow"]), D(r["income"]))
            for r in csv.DictReader(fh)
        ]
    figures = return_figures(series)
    assert figures is not None and figures.twr is not None and figures.xirr is not None
    assert figures.twr_annualised is not None
    assert abs(float(figures.twr) - expected["twr"]) < 1e-4  # 0.01 percentage points
    assert abs(float(figures.xirr) - expected["xirr"]) < 1e-4
    assert abs(float(figures.twr_annualised) - expected["twr_annualised"]) < 1e-4
    assert (figures.start, figures.end) == (series[0].day, series[-1].day)


# --- properties -------------------------------------------------------------------------------

_rate = st.decimals(min_value=D("-0.2"), max_value=D("0.2"), places=3)
_flow = st.decimals(min_value=D("-500"), max_value=D("5000"), places=2)


@settings(max_examples=60, deadline=None)
@given(st.lists(st.tuples(_rate, _flow), min_size=1, max_size=40))
def test_twr_does_not_depend_on_when_money_comes_or_goes(
    steps: list[tuple[Decimal, Decimal]],
) -> None:
    value = D(10000)
    series = [point(0, str(value))]
    growth = D(1)
    for i, (rate, flow) in enumerate(steps, start=1):
        capital = value + flow
        if capital <= 0:  # a flow that would empty the account is not a valid scenario
            flow = D(0)
            capital = value
        value = capital * (1 + rate)
        growth *= 1 + rate
        series.append(DailyPoint(DAY0 + timedelta(days=i), value, flow))
    result = twr(series)
    assert result is not None
    assert abs(result - (growth - 1)) < D("1E-25")


@settings(max_examples=40, deadline=None)
@given(
    st.decimals(min_value=D("100"), max_value=D("100000"), places=2),
    st.decimals(min_value=D("-0.5"), max_value=D("3"), places=3),
    st.integers(min_value=30, max_value=3000),
)
def test_xirr_inverts_compound_growth(amount: Decimal, rate: Decimal, days: int) -> None:
    end = amount * (1 + rate) ** (Decimal(days) / Decimal(365))
    result = xirr([(DAY0, -amount), (DAY0 + timedelta(days=days), end)])
    assert result is not None
    assert abs(result - rate) < D("1E-9")
