"""An account's history as compact per-date summaries (one replay of the ledger).

Valuation, returns, attribution and the simulator all need "what did this account hold, and what
had been put in, on day X". `build_timeline` answers it for every trade date after one pass;
`Timeline.at` finds the entry in force on any day by bisection.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from folio.domain.ledger import CostBasisMethod, TxIn, replay

ZERO = Decimal(0)


@dataclass(frozen=True)
class PositionAt:
    quantity: Decimal
    cost_basis_eur: Decimal
    net_invested_eur: Decimal  # cumulative money put in less taken out
    income_eur: Decimal  # cumulative dividends and interest


@dataclass(frozen=True)
class AccountAt:
    """The account at the end of a trade date. Positions that were ever held are included, also
    once sold (their income and net invested still matter for returns)."""

    day: date
    positions: dict[int, PositionAt]
    net_contributions_eur: Decimal
    external_flows_eur: Decimal
    cash_eur: Decimal
    income_eur: Decimal  # all income, including interest not tied to an instrument
    costs_eur: Decimal  # standalone fees and taxes


@dataclass
class Timeline:
    days: list[date] = field(default_factory=list)
    entries: list[AccountAt] = field(default_factory=list)

    def at(self, day: date) -> AccountAt | None:
        """The entry in force at the end of `day`; None before the first transaction."""
        index = bisect_right(self.days, day)
        return None if index == 0 else self.entries[index - 1]


def build_timeline(txs: Iterable[TxIn], method: CostBasisMethod) -> Timeline:
    timeline = Timeline()
    for day, state in replay(txs, method):
        positions = {
            instrument_id: PositionAt(
                quantity=p.quantity,
                cost_basis_eur=p.cost_basis_eur,
                net_invested_eur=p.net_invested_eur,
                income_eur=p.income_eur,
            )
            for instrument_id, p in state.positions.items()
        }
        timeline.days.append(day)
        timeline.entries.append(
            AccountAt(
                day=day,
                positions=positions,
                net_contributions_eur=state.net_contributions_eur,
                external_flows_eur=state.external_flows_eur,
                cash_eur=state.cash_eur,
                income_eur=state.total_income_eur,
                costs_eur=state.standalone_fees_eur + state.taxes_eur,
            )
        )
    return timeline
