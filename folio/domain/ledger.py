"""Pure ledger logic: lots, cost basis (FIFO or average cost), realized P&L, splits.

No I/O. Transactions are the only source of truth; everything here is derived by replaying
them (`rebuild`). Money and quantities are Decimal end to end. Internal share-splitting of a
cost across lots is quantised to 12 decimal places (never to cents) so that the parts always
add back up to the whole exactly; rounding to cents happens only for display.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from enum import StrEnum

ZERO = Decimal(0)
ONE = Decimal(1)
_SHARE_QUANTUM = Decimal("1E-12")


class TxType(StrEnum):
    BUY = "buy"
    SELL = "sell"
    DIVIDEND = "dividend"
    INTEREST = "interest"
    FEE = "fee"
    TAX = "tax"
    SPLIT = "split"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"


class CostBasisMethod(StrEnum):
    FIFO = "FIFO"
    AVG = "AVG"


class LedgerError(ValueError):
    """A transaction cannot be applied; the message is written for the owner."""


class OversellError(LedgerError):
    def __init__(
        self, tx_id: int, instrument_id: int, requested: Decimal, available: Decimal, on: date
    ) -> None:
        self.tx_id = tx_id
        self.instrument_id = instrument_id
        self.requested = requested
        self.available = available
        self.on = on
        super().__init__(
            f"Cannot sell {requested.normalize():f} units on {on.isoformat()}: "
            f"only {available.normalize():f} are held at that point."
        )


@dataclass(frozen=True)
class TxIn:
    """One ledger event, already converted to EUR by the caller.

    Trades: `quantity` and `price` are positive; `price` is per unit in the trading currency
    and `fx_rate` converts that currency to EUR. `fees_eur` and `taxes_eur` are the trade's
    costs in EUR (the caller converts them with their own rates). `amount_eur` is the EUR
    amount for dividend, interest, fee, tax, deposit and withdrawal, and the carried-over cost
    basis for `transfer_in` (optional). `ratio` is new units per old unit for a split.
    """

    id: int
    type: TxType
    trade_date: date
    instrument_id: int | None = None
    quantity: Decimal = ZERO
    price: Decimal = ZERO
    fx_rate: Decimal = ONE
    fees_eur: Decimal = ZERO
    taxes_eur: Decimal = ZERO
    amount_eur: Decimal | None = None
    ratio: Decimal | None = None


@dataclass
class Lot:
    """The still-open part of one buy (or, under average cost, the pooled holding)."""

    buy_tx_id: int
    instrument_id: int
    trade_date: date
    open_quantity: Decimal
    cost_eur: Decimal
    cost_native: Decimal  # gross price paid in the trading currency, fees excluded


@dataclass(frozen=True)
class LotMatch:
    """Explains one slice of a sell: which lot, how much, and the resulting realized P&L."""

    sell_tx_id: int
    lot_buy_tx_id: int
    instrument_id: int
    quantity: Decimal
    cost_eur: Decimal
    proceeds_eur: Decimal
    realized_pnl_eur: Decimal


@dataclass
class PositionState:
    instrument_id: int
    lots: list[Lot] = field(default_factory=list)
    realized_pnl_eur: Decimal = ZERO
    income_eur: Decimal = ZERO
    invested_eur: Decimal = ZERO  # cumulative acquisition cost (buys and transfers in)
    proceeds_eur: Decimal = ZERO  # cumulative net sale proceeds
    net_invested_eur: Decimal = ZERO  # money put in less money taken out (also by transfers)
    first_trade_date: date | None = None

    @property
    def quantity(self) -> Decimal:
        return sum((lot.open_quantity for lot in self.lots), ZERO)

    @property
    def cost_basis_eur(self) -> Decimal:
        return sum((lot.cost_eur for lot in self.lots), ZERO)

    @property
    def cost_basis_native(self) -> Decimal:
        return sum((lot.cost_native for lot in self.lots), ZERO)

    @property
    def avg_cost_eur(self) -> Decimal | None:
        qty = self.quantity
        return None if qty == 0 else self.cost_basis_eur / qty


@dataclass
class LedgerState:
    method: CostBasisMethod
    positions: dict[int, PositionState] = field(default_factory=dict)
    matches: list[LotMatch] = field(default_factory=list)
    net_contributions_eur: Decimal = ZERO
    other_income_eur: Decimal = ZERO  # interest not tied to an instrument
    standalone_fees_eur: Decimal = ZERO
    taxes_eur: Decimal = ZERO
    # Cash (FR-TX-09). Always computed; an account that does not track cash simply ignores it.
    cash_eur: Decimal = ZERO
    # Money that crossed the account's border: deposits less withdrawals, plus holdings
    # transferred in less holdings transferred out. Net contributions when cash is tracked.
    external_flows_eur: Decimal = ZERO

    def position(self, instrument_id: int) -> PositionState:
        pos = self.positions.get(instrument_id)
        if pos is None:
            pos = self.positions[instrument_id] = PositionState(instrument_id)
        return pos

    @property
    def total_income_eur(self) -> Decimal:
        return self.other_income_eur + sum((p.income_eur for p in self.positions.values()), ZERO)


@contextmanager
def precise() -> Iterator[None]:
    """Plenty of significant digits, so Decimal arithmetic never rounds silently."""
    with localcontext() as ctx:
        ctx.prec = 60
        yield


def share(value: Decimal, part: Decimal, whole: Decimal) -> Decimal:
    """`value * part / whole`, quantised so that `value - share(...)` stays exact."""
    if part == whole:
        return value
    return (value * part / whole).quantize(_SHARE_QUANTUM, ROUND_HALF_EVEN)


# Same-day ordering: a split applies before trades quoted after it; acquisitions before
# disposals, so an export listed newest-first still replays correctly.
_RANK: dict[TxType, int] = {
    TxType.SPLIT: 0,
    TxType.BUY: 1,
    TxType.TRANSFER_IN: 1,
    TxType.SELL: 2,
    TxType.TRANSFER_OUT: 2,
}


def _sort_key(tx: TxIn) -> tuple[date, int, int]:
    return (tx.trade_date, _RANK.get(tx.type, 3), tx.id)


def _need_instrument(tx: TxIn) -> int:
    if tx.instrument_id is None:
        raise LedgerError(f"A {tx.type.value} needs an instrument.")
    return tx.instrument_id


def _need_positive(tx: TxIn, name: str, value: Decimal | None) -> Decimal:
    if value is None or value <= 0:
        raise LedgerError(f"A {tx.type.value} needs a {name} greater than zero.")
    return value


def _add_lot(pos: PositionState, lot: Lot, method: CostBasisMethod) -> None:
    if method is CostBasisMethod.AVG and pos.lots:
        pool = pos.lots[0]  # one pooled holding: every buy merges into it
        pool.open_quantity += lot.open_quantity
        pool.cost_eur += lot.cost_eur
        pool.cost_native += lot.cost_native
    else:
        pos.lots.append(lot)
    pos.invested_eur += lot.cost_eur
    if pos.first_trade_date is None or lot.trade_date < pos.first_trade_date:
        pos.first_trade_date = lot.trade_date


@dataclass(frozen=True)
class _Consumed:
    lot_buy_tx_id: int
    quantity: Decimal
    cost_eur: Decimal


def _consume(pos: PositionState, tx: TxIn, quantity: Decimal) -> list[_Consumed]:
    available = pos.quantity
    if quantity > available:
        raise OversellError(tx.id, pos.instrument_id, quantity, available, tx.trade_date)
    taken: list[_Consumed] = []
    remaining = quantity
    for lot in list(pos.lots):  # FIFO order; under AVG there is a single pooled lot
        if remaining == 0:
            break
        take = min(lot.open_quantity, remaining)
        cost = share(lot.cost_eur, take, lot.open_quantity)
        native = share(lot.cost_native, take, lot.open_quantity)
        lot.cost_eur -= cost
        lot.cost_native -= native
        lot.open_quantity -= take
        remaining -= take
        taken.append(_Consumed(lot.buy_tx_id, take, cost))
        if lot.open_quantity == 0:
            pos.lots.remove(lot)
    return taken


def _apply_buy(state: LedgerState, tx: TxIn) -> None:
    instrument = _need_instrument(tx)
    qty = _need_positive(tx, "quantity", tx.quantity)
    if tx.price < 0:
        raise LedgerError("A buy cannot have a negative price.")
    cost = qty * tx.price * tx.fx_rate + tx.fees_eur + tx.taxes_eur
    lot = Lot(tx.id, instrument, tx.trade_date, qty, cost, qty * tx.price)
    pos = state.position(instrument)
    _add_lot(pos, lot, state.method)
    pos.net_invested_eur += cost
    state.net_contributions_eur += cost
    state.cash_eur -= cost


def _apply_sell(state: LedgerState, tx: TxIn) -> None:
    instrument = _need_instrument(tx)
    qty = _need_positive(tx, "quantity", tx.quantity)
    if tx.price < 0:
        raise LedgerError("A sell cannot have a negative price.")
    pos = state.position(instrument)
    net = qty * tx.price * tx.fx_rate - tx.fees_eur - tx.taxes_eur
    taken = _consume(pos, tx, qty)
    allocated = ZERO
    total_cost = ZERO
    for i, piece in enumerate(taken):
        last = i == len(taken) - 1
        proceeds = net - allocated if last else share(net, piece.quantity, qty)
        allocated += proceeds
        total_cost += piece.cost_eur
        state.matches.append(
            LotMatch(
                tx.id,
                piece.lot_buy_tx_id,
                instrument,
                piece.quantity,
                piece.cost_eur,
                proceeds,
                proceeds - piece.cost_eur,
            )
        )
    pos.realized_pnl_eur += net - total_cost
    pos.proceeds_eur += net
    pos.net_invested_eur -= net
    state.net_contributions_eur -= net
    state.cash_eur += net


def _apply_transfer_in(state: LedgerState, tx: TxIn) -> None:
    instrument = _need_instrument(tx)
    qty = _need_positive(tx, "quantity", tx.quantity)
    cost = tx.amount_eur if tx.amount_eur is not None else qty * tx.price * tx.fx_rate
    lot = Lot(tx.id, instrument, tx.trade_date, qty, cost, qty * tx.price)
    pos = state.position(instrument)
    _add_lot(pos, lot, state.method)
    pos.net_invested_eur += cost
    state.net_contributions_eur += cost
    state.external_flows_eur += cost  # holdings arrive without cash


def _apply_transfer_out(state: LedgerState, tx: TxIn) -> None:
    instrument = _need_instrument(tx)
    qty = _need_positive(tx, "quantity", tx.quantity)
    pos = state.position(instrument)
    taken = _consume(pos, tx, qty)
    moved = ZERO
    for piece in taken:  # moving holdings is not a sale: proceeds equal cost, so no P&L
        moved += piece.cost_eur
        state.matches.append(
            LotMatch(
                tx.id,
                piece.lot_buy_tx_id,
                instrument,
                piece.quantity,
                piece.cost_eur,
                piece.cost_eur,
                ZERO,
            )
        )
    pos.net_invested_eur -= moved
    state.net_contributions_eur -= moved
    state.external_flows_eur -= moved


def _apply_split(state: LedgerState, tx: TxIn) -> None:
    instrument = _need_instrument(tx)
    ratio = _need_positive(tx, "ratio", tx.ratio)
    for lot in state.position(instrument).lots:
        lot.open_quantity *= ratio  # cost basis is untouched: only the unit count changes


def _apply_income(state: LedgerState, tx: TxIn) -> None:
    amount = _need_positive(tx, "amount", tx.amount_eur)
    if tx.instrument_id is not None:
        state.position(tx.instrument_id).income_eur += amount
    elif tx.type is TxType.DIVIDEND:
        raise LedgerError("A dividend needs an instrument.")
    else:
        state.other_income_eur += amount
    state.taxes_eur += tx.taxes_eur  # withholding tax
    state.standalone_fees_eur += tx.fees_eur
    state.cash_eur += amount - tx.taxes_eur - tx.fees_eur


def _apply_cash_flow(state: LedgerState, tx: TxIn) -> None:
    amount = _need_positive(tx, "amount", tx.amount_eur)
    if tx.type is TxType.FEE:
        state.standalone_fees_eur += amount
        state.cash_eur -= amount
    elif tx.type is TxType.TAX:
        state.taxes_eur += amount
        state.cash_eur -= amount
    elif tx.type is TxType.DEPOSIT:
        state.net_contributions_eur += amount
        state.external_flows_eur += amount
        state.cash_eur += amount
    else:
        state.net_contributions_eur -= amount
        state.external_flows_eur -= amount
        state.cash_eur -= amount


_HANDLERS = {
    TxType.BUY: _apply_buy,
    TxType.SELL: _apply_sell,
    TxType.TRANSFER_IN: _apply_transfer_in,
    TxType.TRANSFER_OUT: _apply_transfer_out,
    TxType.SPLIT: _apply_split,
    TxType.DIVIDEND: _apply_income,
    TxType.INTEREST: _apply_income,
    TxType.FEE: _apply_cash_flow,
    TxType.TAX: _apply_cash_flow,
    TxType.DEPOSIT: _apply_cash_flow,
    TxType.WITHDRAWAL: _apply_cash_flow,
}


def rebuild(txs: Iterable[TxIn], method: CostBasisMethod = CostBasisMethod.FIFO) -> LedgerState:
    """Replay posted transactions into lots, matches and positions.

    Deterministic and independent of input order: events are sorted by trade date, then by
    kind (splits, acquisitions, disposals, the rest), then by id.
    """
    with precise():
        state = LedgerState(method=method)
        for tx in sorted(txs, key=_sort_key):
            _HANDLERS[tx.type](state, tx)
    return state


@dataclass(frozen=True)
class SellPreview:
    matches: tuple[LotMatch, ...]
    net_proceeds_eur: Decimal
    cost_eur: Decimal
    realized_pnl_eur: Decimal
    realized_pct: Decimal | None
    remaining_quantity: Decimal
    remaining_cost_basis_eur: Decimal


def preview_sell(
    existing: Iterable[TxIn], sell: TxIn, method: CostBasisMethod = CostBasisMethod.FIFO
) -> SellPreview:
    """What a sell would do, computed by replaying it through `rebuild`.

    Using the same code path as the saved ledger is what makes the preview equal the saved
    result to the cent. Raises OversellError when the sell is larger than the holding.
    """
    if sell.type is not TxType.SELL:
        raise LedgerError("Only a sell can be previewed.")
    history = list(existing)
    if any(t.id == sell.id for t in history):
        raise ValueError("The previewed sell needs an id that no saved transaction uses.")
    state = rebuild([*history, sell], method)
    with precise():
        matches = tuple(m for m in state.matches if m.sell_tx_id == sell.id)
        cost = sum((m.cost_eur for m in matches), ZERO)
        net = sum((m.proceeds_eur for m in matches), ZERO)
        pos = state.position(_need_instrument(sell))
        pnl = net - cost
        return SellPreview(
            matches=matches,
            net_proceeds_eur=net,
            cost_eur=cost,
            realized_pnl_eur=pnl,
            realized_pct=None if cost == 0 else pnl / cost,
            remaining_quantity=pos.quantity,
            remaining_cost_basis_eur=pos.cost_basis_eur,
        )
