"""How numbers are written in text the app produces for the owner to read (ADR 0052).

Nothing the owner reads shows more than two decimals, whatever the calculation used. Values that
are stored, exported or sent to the API are not passed through here; only sentences are.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Final

_CENT: Final = Decimal("0.01")


def two(value: Decimal | int | str | None, *, trim: bool = False) -> str:
    """`value` rounded half up to two decimals: "98.54", "110.00". With `trim` a whole number
    stays whole and a trailing zero goes ("4", "1.5"), for units and ratios. Nothing is "–"."""
    if value is None:
        return "–"
    text = f"{Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP):f}"
    return text.rstrip("0").rstrip(".") if trim else text


def small(value: Decimal | int | str) -> str:
    """An amount, or "< 0.01" for one that is above zero but less than a cent (the cost of one
    AI call), which "0.00" would make look free."""
    amount = Decimal(value)
    if 0 < amount < _CENT / 2:
        return "< 0.01"
    return two(amount)
