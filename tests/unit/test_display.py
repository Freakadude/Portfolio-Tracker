"""Text for the owner never shows more than two decimals (ADR 0052)."""

from decimal import Decimal

import pytest

from folio.display import small, two


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (Decimal("98.5432"), "98.54"),
        (Decimal("98.555"), "98.56"),  # half up, not to even
        (Decimal("110"), "110.00"),
        (Decimal("0.004"), "0.00"),
        (Decimal("-1.239"), "-1.24"),
        ("2.5", "2.50"),
        (7, "7.00"),
        (None, "–"),
    ],
)
def test_two_rounds_half_up_to_two_decimals(value: object, text: str) -> None:
    assert two(value) == text  # type: ignore[arg-type]


def test_trim_keeps_whole_numbers_whole_and_drops_trailing_zeros() -> None:
    assert two(Decimal("4"), trim=True) == "4"
    assert two(Decimal("1.50"), trim=True) == "1.5"
    assert two(Decimal("1.234"), trim=True) == "1.23"
    assert two(Decimal("100"), trim=True) == "100"
    assert two(Decimal("0.001"), trim=True) == "0"


def test_a_part_of_a_cent_is_not_written_as_nothing() -> None:
    assert small(Decimal("0.0042")) == "< 0.01"
    assert small(Decimal("0.0213")) == "0.02"
    assert small(Decimal(0)) == "0.00"
