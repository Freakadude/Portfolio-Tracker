"""Property tests for the five ledger invariants (spec section 5) and friends."""

import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import folio.domain
from folio.domain import (
    CostBasisMethod,
    LedgerState,
    OversellError,
    TxIn,
    TxType,
    preview_sell,
    rebuild,
)
from folio.domain.ledger import precise

INSTRUMENTS = (1, 2)
METHODS = st.sampled_from(list(CostBasisMethod))
PROPS = settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])

prices = st.decimals(Decimal("0.01"), Decimal("1000"), places=2)
fx_rates = st.decimals(Decimal("0.5"), Decimal("1.5"), places=4)
fees = st.decimals(Decimal(0), Decimal(10), places=2)


@st.composite
def sequences(draw: st.DrawFn) -> list[TxIn]:
    """A valid history: sells never exceed the holding at that moment. Each event is on its
    own day so same-day ordering rules do not interfere with the bookkeeping here."""
    held = {i: Decimal(0) for i in INSTRUMENTS}
    txs: list[TxIn] = []
    day = date(2024, 1, 1)
    for tx_id in range(1, draw(st.integers(1, 25)) + 1):
        day += timedelta(days=draw(st.integers(1, 5)))
        instrument = draw(st.sampled_from(INSTRUMENTS))
        kind = draw(st.sampled_from(["buy", "buy", "sell", "split", "dividend"]))
        if kind == "sell" and held[instrument] > 0:
            qty = Decimal(draw(st.integers(1, int(held[instrument]))))
            held[instrument] -= qty
            txs.append(
                TxIn(
                    tx_id,
                    TxType.SELL,
                    day,
                    instrument,
                    qty,
                    draw(prices),
                    draw(fx_rates),
                    draw(fees),
                )
            )
        elif kind == "split" and held[instrument] > 0:
            ratio = Decimal(draw(st.integers(2, 4)))
            held[instrument] *= ratio
            txs.append(TxIn(tx_id, TxType.SPLIT, day, instrument, ratio=ratio))
        elif kind == "dividend" and held[instrument] > 0:
            txs.append(
                TxIn(
                    tx_id,
                    TxType.DIVIDEND,
                    day,
                    instrument,
                    amount_eur=draw(prices),
                    taxes_eur=draw(fees),
                )
            )
        else:
            qty = Decimal(draw(st.integers(1, 500)))
            held[instrument] += qty
            txs.append(
                TxIn(
                    tx_id,
                    TxType.BUY,
                    day,
                    instrument,
                    qty,
                    draw(prices),
                    draw(fx_rates),
                    draw(fees),
                )
            )
    return txs


def independent_quantity(txs: list[TxIn], instrument: int) -> Decimal:
    qty = Decimal(0)
    for tx in sorted(txs, key=lambda t: (t.trade_date, t.id)):
        if tx.instrument_id != instrument:
            continue
        if tx.type is TxType.BUY:
            qty += tx.quantity
        elif tx.type is TxType.SELL:
            qty -= tx.quantity
        elif tx.type is TxType.SPLIT and tx.ratio is not None:
            qty *= tx.ratio
    return qty


def snapshot(state: LedgerState) -> tuple[object, ...]:
    return (
        state.method,
        {
            i: (
                p.realized_pnl_eur,
                p.income_eur,
                p.invested_eur,
                p.proceeds_eur,
                [
                    (lot.buy_tx_id, lot.open_quantity, lot.cost_eur, lot.cost_native)
                    for lot in p.lots
                ],
            )
            for i, p in state.positions.items()
        },
        state.matches,
        state.net_contributions_eur,
        state.other_income_eur,
        state.standalone_fees_eur,
        state.taxes_eur,
    )


@PROPS
@given(sequences(), METHODS)
def test_invariant_1_lot_quantities_sum_to_position_quantity(
    txs: list[TxIn], method: CostBasisMethod
) -> None:
    state = rebuild(txs, method)
    for instrument in INSTRUMENTS:
        pos = state.position(instrument)
        assert pos.quantity == independent_quantity(txs, instrument)
        assert pos.quantity == sum((lot.open_quantity for lot in pos.lots), Decimal(0))
        assert all(lot.open_quantity > 0 for lot in pos.lots)


@PROPS
@given(sequences(), METHODS, prices, fx_rates)
def test_invariant_2_realized_plus_unrealized_equals_value_plus_proceeds_minus_cost(
    txs: list[TxIn], method: CostBasisMethod, price: Decimal, fx: Decimal
) -> None:
    state = rebuild(txs, method)
    with precise():
        for instrument in INSTRUMENTS:
            pos = state.position(instrument)
            value = pos.quantity * price * fx
            unrealized = value - pos.cost_basis_eur
            assert pos.realized_pnl_eur + unrealized == value + pos.proceeds_eur - pos.invested_eur


@PROPS
@given(sequences(), METHODS)
def test_matches_conserve_cost_and_explain_realized_pnl(
    txs: list[TxIn], method: CostBasisMethod
) -> None:
    state = rebuild(txs, method)
    for instrument in INSTRUMENTS:
        pos = state.position(instrument)
        mine = [m for m in state.matches if m.instrument_id == instrument]
        assert sum((m.cost_eur for m in mine), Decimal(0)) + pos.cost_basis_eur == pos.invested_eur
        assert sum((m.realized_pnl_eur for m in mine), Decimal(0)) == pos.realized_pnl_eur
        assert sum((m.proceeds_eur for m in mine), Decimal(0)) == pos.proceeds_eur


@PROPS
@given(sequences(), METHODS)
def test_invariant_3_a_sell_can_never_exceed_the_open_quantity(
    txs: list[TxIn], method: CostBasisMethod
) -> None:
    state = rebuild(txs, method)
    for instrument in INSTRUMENTS:
        held = state.position(instrument).quantity
        too_much = TxIn(10_000, TxType.SELL, date(2030, 1, 1), instrument, held + 1, Decimal(1))
        with pytest.raises(OversellError) as err:
            rebuild([*txs, too_much], method)
        assert err.value.available == held and err.value.requested == held + 1


@PROPS
@given(sequences(), METHODS, st.integers(2, 6), prices)
def test_invariant_4_split_keeps_total_cost_and_market_value(
    txs: list[TxIn], method: CostBasisMethod, ratio: int, price: Decimal
) -> None:
    before = rebuild(txs, method)
    split = TxIn(10_000, TxType.SPLIT, date(2030, 1, 1), 1, ratio=Decimal(ratio))
    after = rebuild([*txs, split], method)
    b, a = before.position(1), after.position(1)
    assert a.cost_basis_eur == b.cost_basis_eur
    assert a.quantity == b.quantity * ratio
    with precise():
        # Market value: units times price is unchanged when the price falls by the split ratio.
        assert (a.quantity * price) / ratio == b.quantity * price
    assert after.position(2) == before.position(2)


@PROPS
@given(sequences(), METHODS, st.randoms(use_true_random=False))
def test_invariant_5_rebuild_is_repeatable_and_order_independent(
    txs: list[TxIn], method: CostBasisMethod, rng: object
) -> None:
    first = snapshot(rebuild(txs, method))
    assert snapshot(rebuild(txs, method)) == first
    shuffled = list(txs)
    rng.shuffle(shuffled)  # type: ignore[attr-defined]
    assert snapshot(rebuild(shuffled, method)) == first


@PROPS
@given(sequences(), METHODS, st.data())
def test_preview_equals_the_saved_result_to_the_cent(
    txs: list[TxIn], method: CostBasisMethod, data: st.DataObject
) -> None:
    state = rebuild(txs, method)
    held = state.position(1).quantity
    if held < 1:
        return
    qty = Decimal(data.draw(st.integers(1, int(held))))
    sell = TxIn(
        10_000,
        TxType.SELL,
        date(2030, 1, 1),
        1,
        qty,
        data.draw(prices),
        data.draw(fx_rates),
        data.draw(fees),
    )
    preview = preview_sell(txs, sell, method)
    saved = rebuild([*txs, sell], method)
    after, before = saved.position(1), state.position(1)
    assert preview.realized_pnl_eur == after.realized_pnl_eur - before.realized_pnl_eur
    assert preview.net_proceeds_eur == after.proceeds_eur - before.proceeds_eur
    assert preview.remaining_quantity == after.quantity == held - qty
    assert preview.remaining_cost_basis_eur == after.cost_basis_eur


@PROPS
@given(sequences())
def test_fifo_and_average_cost_agree_on_total_cost(txs: list[TxIn]) -> None:
    fifo, avg = rebuild(txs, CostBasisMethod.FIFO), rebuild(txs, CostBasisMethod.AVG)
    for instrument in INSTRUMENTS:
        f, a = fifo.position(instrument), avg.position(instrument)
        assert f.quantity == a.quantity
        assert f.invested_eur == a.invested_eur
        # The method only moves cost between "realized" and "still open": the overall result
        # (realized plus unrealized at any price) is the same, which means realized minus
        # open cost is method independent.
        assert f.realized_pnl_eur - f.cost_basis_eur == a.realized_pnl_eur - a.cost_basis_eur
    assert fifo.net_contributions_eur == avg.net_contributions_eur


def test_no_floats_in_the_domain_package() -> None:
    package = Path(folio.domain.__file__).parent
    for source in package.glob("*.py"):
        code = re.sub(r'""".*?"""|#.*', "", source.read_text(encoding="utf-8"), flags=re.S)
        assert not re.search(r"\bfloat\b|\d\.\d+(?!\d*['\"])", code.replace("Decimal(", "")), (
            f"{source.name} must not use floats"
        )
