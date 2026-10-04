from datetime import date
from decimal import Decimal

import pytest

from folio.analytics.valuation import (
    PERIODS,
    DayPoint,
    PricePoint,
    make_day_point,
    period_figures,
    pnl_ratio_since_start,
    resolve_period,
    subtract_months,
    value_holding,
)

D = Decimal
TODAY = date(2024, 4, 10)


@pytest.mark.parametrize(
    ("day", "months", "expected"),
    [
        (date(2024, 3, 31), 1, date(2024, 2, 29)),  # a leap February, clamped
        (date(2025, 3, 31), 1, date(2025, 2, 28)),
        (date(2024, 1, 15), 2, date(2023, 11, 15)),  # across a year boundary
        (date(2024, 4, 10), 12, date(2023, 4, 10)),
        (date(2024, 5, 31), 3, date(2024, 2, 29)),
        (date(2024, 12, 31), 60, date(2019, 12, 31)),
    ],
)
def test_subtracting_months_clamps_to_the_month_end(day: date, months: int, expected: date) -> None:
    assert subtract_months(day, months) == expected


@pytest.mark.parametrize(
    ("key", "start"),
    [
        ("1D", date(2024, 4, 9)),
        ("1W", date(2024, 4, 3)),
        ("1M", date(2024, 3, 10)),
        ("3M", date(2024, 1, 10)),
        ("YTD", date(2023, 12, 31)),  # the last day of the previous year
        ("1Y", date(2023, 4, 10)),
        ("3Y", date(2021, 4, 10)),
        ("5Y", date(2019, 4, 10)),
        ("MAX", date(2023, 5, 31)),  # the day before the first transaction
    ],
)
def test_period_starts(key: str, start: date) -> None:
    assert resolve_period(key, TODAY, date(2023, 6, 1)) == (start, TODAY)
    assert resolve_period(key.lower(), TODAY, date(2023, 6, 1)) == (
        start,
        TODAY,
    )  # case-insensitive


def test_max_without_any_transaction_is_a_single_day() -> None:
    assert resolve_period("MAX", TODAY, None) == (date(2024, 4, 9), TODAY)


def test_custom_periods_are_validated() -> None:
    assert resolve_period("custom", TODAY, None, date(2024, 1, 3), date(2024, 1, 10)) == (
        date(2024, 1, 3),
        date(2024, 1, 10),
    )
    with pytest.raises(ValueError, match="needs both a start and an end"):
        resolve_period("CUSTOM", TODAY, None, date(2024, 1, 3), None)
    with pytest.raises(ValueError, match="cannot be after its end"):
        resolve_period("CUSTOM", TODAY, None, date(2024, 2, 1), date(2024, 1, 1))


def test_unknown_period_names_the_valid_ones() -> None:
    with pytest.raises(ValueError, match="Unknown period 'WEEK'") as err:
        resolve_period("week", TODAY, None)
    assert all(key in str(err.value) for key in PERIODS)


def test_holding_value_and_missing_price() -> None:
    price = PricePoint(date(2024, 4, 10), D("60"), D("0.8"))
    held = value_holding(1, 7, D(10), D(451), price)
    assert held.value_eur == D(480) and held.price == price
    assert value_holding(1, 7, D(10), D(451), None).value_eur is None


def test_a_day_point_counts_only_valued_holdings() -> None:
    price = PricePoint(date(2024, 4, 10), D("100"), D(1))
    holdings = [value_holding(1, 1, D(2), D(180), price), value_holding(1, 2, D(5), D(40), None)]
    point = make_day_point(TODAY, holdings, D(220), D(4), D(1))
    assert point.value_eur == D(200) and point.unvalued == 1
    assert point.total_pnl_eur == D(200) - D(220) + D(4) - D(
        1
    )  # value - contributions + income - costs


def point(
    day: date, value: str, contributions: str, income: str = "0", costs: str = "0"
) -> DayPoint:
    return DayPoint(day, D(value), D(contributions), D(income), D(costs), 0)


def test_period_figures_by_hand() -> None:
    start = point(date(2024, 1, 1), "1000", "900", income="10", costs="1")
    end = point(date(2024, 2, 1), "1500", "1200", income="15", costs="3")
    f = period_figures(start, end)
    assert (f.net_flows_eur, f.income_eur, f.costs_eur) == (300, 5, 2)
    # value change 500, less the 300 put in, plus 5 of income, less 2 of costs
    assert f.pnl_eur == 203
    assert f.pnl_ratio == D(203) / D(1300)  # over the capital at work: 1000 + 300
    assert (f.start, f.end, f.value_start_eur, f.value_end_eur) == (start.day, end.day, 1000, 1500)


def test_withdrawals_are_negative_flows() -> None:
    f = period_figures(
        point(date(2024, 1, 1), "1000", "1000"), point(date(2024, 2, 1), "700", "600")
    )
    assert f.net_flows_eur == -400 and f.pnl_eur == D(700 - 1000 + 400)  # 100 gained, 400 taken out
    assert f.pnl_ratio == D(100) / D(600)


def test_ratio_is_undefined_without_capital() -> None:
    nothing = period_figures(point(date(2024, 1, 1), "0", "0"), point(date(2024, 2, 1), "0", "0"))
    assert nothing.pnl_eur == 0 and nothing.pnl_ratio is None
    all_out = period_figures(
        point(date(2024, 1, 1), "100", "100"), point(date(2024, 2, 1), "0", "-100")
    )
    assert all_out.pnl_ratio is None  # the capital at work (start value plus flows) is not positive


def test_total_ratio_is_over_the_money_put_in() -> None:
    end = point(date(2024, 4, 10), "1188", "1098", income="3")
    assert end.total_pnl_eur == 93
    assert pnl_ratio_since_start(end) == D(93) / D(1098)
    assert pnl_ratio_since_start(point(date(2024, 4, 10), "0", "0")) is None
    assert pnl_ratio_since_start(point(date(2024, 4, 10), "50", "-10")) is None
