"""Collecting what a run has seen, for the code gate (FR-AG-03).

Every tool result goes through here: the ids of signals and news stories it showed, the tools
called, the macro series and web pages seen, and every number it contained. The gate later
accepts a citation or a figure only if it is in this record.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from folio.agent.validate import Calc, Facts


def numbers_in(value: Any) -> set[Decimal]:
    """Every number in a JSON-like structure, whether it is a number or a numeric string."""
    found: set[Decimal] = set()
    if isinstance(value, bool) or value is None:
        return found
    if isinstance(value, int | Decimal):
        found.add(Decimal(value))
    elif isinstance(value, float):
        found.add(Decimal(str(value)))
    elif isinstance(value, str):
        try:
            number = Decimal(value.strip())
        except InvalidOperation:
            return found
        if number.is_finite():
            found.add(number)
    elif isinstance(value, dict):
        for item in value.values():
            found |= numbers_in(item)
    elif isinstance(value, list | tuple):
        for item in value:
            found |= numbers_in(item)
    return found


class FactsBuilder:
    """What the run has seen so far; `freeze()` gives the gate its view."""

    def __init__(self) -> None:
        self.signals: dict[str, datetime] = {}
        self.clusters: dict[str, datetime] = {}
        self.tools: set[str] = set()
        self.macro: set[str] = set()
        self.urls: set[str] = set()
        self.numbers: set[Decimal] = set()
        self.calculations: dict[str, Calc] = {}

    def add_numbers(self, value: Any) -> None:
        self.numbers |= numbers_in(value)

    def freeze(self) -> Facts:
        return Facts(
            signals=dict(self.signals),
            clusters=dict(self.clusters),
            tools=frozenset(self.tools),
            macro=frozenset(self.macro),
            urls=frozenset(self.urls),
            numbers=frozenset(self.numbers),
            calculations=dict(self.calculations),
        )
