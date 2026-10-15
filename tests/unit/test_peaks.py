"""The peak figures (ADR 0063): the arithmetic, without a database."""

from decimal import Decimal

import pytest

from folio.peaks import fall_off, peak_value

D = Decimal


@pytest.mark.parametrize(
    ("last", "peak", "expected"),
    [
        ("108", "130", "-0.169231"),
        ("130", "130", "0"),
        ("150", "130", "0"),  # never above the peak
        ("100", "0", "0"),  # nothing to measure against
    ],
)
def test_the_fall_off_is_the_last_price_against_the_peak(
    last: str, peak: str, expected: str
) -> None:
    assert fall_off(D(last), D(peak)) == D(expected)


def test_the_peak_value_is_todays_holding_at_the_peak_price() -> None:
    # 11 units worth 1188 at 108: at 130 they would fetch 1430
    assert peak_value(D("1188"), D("108"), D("130")) == D("1430")
    assert peak_value(None, D("108"), D("130")) is None
    assert peak_value(D("1188"), D("0"), D("130")) is None
