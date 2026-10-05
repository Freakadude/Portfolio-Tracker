from decimal import Decimal

import pytest

from folio.analytics.simulate import SimulationError, Trade, simulate

D = Decimal


def test_buys_and_sells_change_quantities_values_and_the_cash_needed() -> None:
    result = simulate(
        {1: D(10), 2: D(4)},
        {1: D(100), 2: D(50), 3: D(20)},
        [
            Trade(3, D(10), D(20)),  # a new holding, 200
            Trade(1, D(-2), D(100), fees_eur=D(1)),  # 200 freed, 1 fee
        ],
    )
    assert result.cash_needed_eur == D("1")  # 200 - 200 + 1
    assert (result.total_before_eur, result.total_after_eur) == (D(1200), D(1200))
    by_id = {p.instrument_id: p for p in result.positions}
    assert (by_id[1].quantity_before, by_id[1].quantity_after) == (D(10), D(8))
    assert (by_id[1].value_before_eur, by_id[1].value_after_eur) == (D(1000), D(800))
    assert (by_id[3].quantity_before, by_id[3].value_after_eur) == (D(0), D(200))
    assert by_id[2].value_after_eur == D(200)  # untouched


def test_positions_are_valued_at_market_not_at_the_assumed_trade_price() -> None:
    result = simulate({1: D(10)}, {1: D(100)}, [Trade(1, D(5), D(90))])  # bought at 90
    assert result.cash_needed_eur == D(450)
    assert result.total_after_eur == D(1500)  # 15 x the market price of 100


def test_trades_are_applied_in_order_so_a_buy_can_fund_a_sale() -> None:
    result = simulate({}, {1: D(10)}, [Trade(1, D(5), D(10)), Trade(1, D(-5), D(10))])
    assert result.positions[0].quantity_after == 0 and result.cash_needed_eur == 0


def test_selling_more_than_is_held_is_refused() -> None:
    with pytest.raises(SimulationError) as caught:
        simulate({1: D(3)}, {1: D(10)}, [Trade(1, D(-4), D(10))])
    assert (caught.value.instrument_id, caught.value.held, caught.value.wanted) == (1, D(3), D(4))
    with pytest.raises(SimulationError):
        simulate({}, {1: D(10)}, [Trade(1, D(-1), D(10))])


def test_a_holding_without_any_price_is_left_out_of_the_comparison() -> None:
    result = simulate({1: D(10), 2: D(5)}, {1: D(100)}, [])
    assert [p.instrument_id for p in result.positions] == [1]
    assert result.total_before_eur == D(1000)


def test_the_inputs_are_never_changed() -> None:
    quantities = {1: D(10)}
    simulate(quantities, {1: D(100)}, [Trade(1, D(5), D(100))])
    assert quantities == {1: D(10)}
