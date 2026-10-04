"""ISIN validation: two-letter country code, nine alphanumerics, and the Luhn check digit."""

from __future__ import annotations

import re

_FORMAT = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def normalize_isin(raw: str) -> str:
    """Uppercase and validated, or ValueError with a message for the owner."""
    isin = raw.strip().upper().replace(" ", "")
    if not _FORMAT.match(isin):
        raise ValueError(
            "An ISIN has 12 characters: two letters, nine letters or digits, and a check digit "
            "(for example IE00B5BMR087)."
        )
    digits = "".join(str(int(c, 36)) for c in isin)  # letters become 10..35
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            n = n - 9 if n > 9 else n
        total += n
    if total % 10 != 0:
        raise ValueError(f"{isin} has a wrong check digit. Check it for typing mistakes.")
    return isin
