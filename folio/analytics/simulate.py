"""The what-if simulator (FR-PF-09): hypothetical buys and sells on top of what is held.

Pure and read-only by construction: it takes quantities and prices and returns new numbers; it
has no access to the ledger and writes nothing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from folio.display import two

ZERO = Decimal(0)


@dataclass(frozen=True)
class Trade:
    instrument_id: int
    quantity: Decimal  # positive buys, negative sells
    price_eur: Decimal  # the price this trade is assumed to be made at
    fees_eur: Decimal = ZERO


class SimulationError(ValueError):
    def __init__(self, instrument_id: int, held: Decimal, wanted: Decimal) -> None:
        self.instrument_id = instrument_id
        self.held = held
        self.wanted = wanted
        super().__init__(
            f"Instrument {instrument_id}: holds {two(held, trim=True)}, "
            f"a sale needs {two(wanted, trim=True)}."
        )


@dataclass(frozen=True)
class SimulatedPosition:
    instrument_id: int
    quantity_before: Decimal
    quantity_after: Decimal
    value_before_eur: Decimal
    value_after_eur: Decimal


@dataclass(frozen=True)
class Simulation:
    positions: list[SimulatedPosition]
    cash_needed_eur: Decimal  # positive: money to find; negative: money freed
    total_before_eur: Decimal
    total_after_eur: Decimal


def simulate(
    quantities: Mapping[int, Decimal],
    market_prices: Mapping[int, Decimal],
    trades: Sequence[Trade],
) -> Simulation:
    """Apply `trades` to the holdings. Positions are valued at market prices before and after
    (the trade price only decides how much cash moves), so the change in allocation is not
    muddied by the price paid. Selling more than is held raises `SimulationError`."""
    after = dict(quantities)
    cash = ZERO
    traded_at: dict[int, Decimal] = {}
    for trade in trades:
        held = after.get(trade.instrument_id, ZERO)
        new = held + trade.quantity
        if new < 0:
            raise SimulationError(trade.instrument_id, held, -trade.quantity)
        after[trade.instrument_id] = new
        cash += trade.quantity * trade.price_eur + trade.fees_eur
        traded_at.setdefault(trade.instrument_id, trade.price_eur)

    positions: list[SimulatedPosition] = []
    total_before = total_after = ZERO
    for instrument_id in sorted(set(quantities) | set(after)):
        price = market_prices.get(instrument_id, traded_at.get(instrument_id))
        if price is None:
            continue  # held but unpriced: it has no value to compare
        before_q = quantities.get(instrument_id, ZERO)
        after_q = after.get(instrument_id, ZERO)
        positions.append(
            SimulatedPosition(instrument_id, before_q, after_q, before_q * price, after_q * price)
        )
        total_before += before_q * price
        total_after += after_q * price
    return Simulation(positions, cash, total_before, total_after)
