from datetime import date
from decimal import Decimal

from folio.domain import (
    CostBasisMethod,
    LedgerState,
    Quote,
    TxIn,
    TxType,
    portfolio_metrics,
    position_metrics,
    rebuild,
    round_cents,
)
from folio.domain.ledger import precise

D = Decimal


def _state() -> LedgerState:
    return rebuild(
        [
            TxIn(1, TxType.BUY, date(2024, 1, 2), 1, D(10), D(50), D("0.9"), fees_eur=D(1)),
            TxIn(2, TxType.DIVIDEND, date(2024, 2, 1), 1, amount_eur=D(4)),
            TxIn(3, TxType.FEE, date(2024, 2, 2), amount_eur=D(2)),
        ],
        CostBasisMethod.FIFO,
    )


def test_position_metrics_against_a_hand_computed_example() -> None:
    state = _state()
    quote = Quote(D(60), D("0.8"), prev_price=D(58), prev_fx_rate=D("0.85"))
    m = position_metrics(state.position(1), quote)
    assert m.quantity == D(10)
    assert m.cost_basis_eur == D(451)
    assert m.avg_cost_eur == D("45.1")
    assert m.market_value_eur == D(480)
    assert m.unrealized_pnl_eur == D(29)
    with precise():
        assert m.unrealized_pct == D(29) / D(451)
    assert m.income_eur == D(4)
    assert m.total_return_eur == D(33)  # 29 unrealized + 0 realized + 4 income
    assert m.day_change_eur == D(-13)  # 480 - 10 * 58 * 0.85
    with precise():
        assert m.total_return_pct == D(33) / D(451)
        assert m.day_change_pct == D(-13) / D(493)
    # the same position seen in the trading currency, so price and currency moves separate
    assert m.market_value_native == D(600)
    assert m.cost_basis_native == D(500)
    assert m.unrealized_pnl_native == D(100)


def test_day_change_is_unknown_without_a_previous_close() -> None:
    m = position_metrics(_state().position(1), Quote(D(60), D("0.8")))
    assert m.day_change_eur is None and m.day_change_pct is None


def test_portfolio_totals_follow_the_spec_formula() -> None:
    state = _state()
    quotes = {1: Quote(D(60), D("0.8"), D(58), D("0.85"))}
    p = portfolio_metrics(state, quotes)
    assert p.market_value_eur == D(480)
    assert p.net_contributions_eur == D(451)
    # value - contributions + income - standalone fees - taxes = 480 - 451 + 4 - 2 - 0
    assert p.total_pnl_eur == D(31)
    with precise():
        assert p.total_pnl_pct == D(31) / D(451)
    assert p.day_change_eur == D(-13)


def test_a_position_without_a_quote_makes_the_day_change_unknown() -> None:
    p = portfolio_metrics(_state(), {})
    assert p.market_value_eur == D(0)
    assert p.day_change_eur is None


def test_closed_positions_do_not_need_a_quote() -> None:
    state = rebuild(
        [
            TxIn(1, TxType.BUY, date(2024, 1, 2), 1, D(1), D(10)),
            TxIn(2, TxType.SELL, date(2024, 1, 3), 1, D(1), D(12)),
        ]
    )
    p = portfolio_metrics(state, {})
    assert p.day_change_eur == D(0)
    assert p.total_pnl_eur == D(2)  # all of it realized


def test_display_rounding_is_half_even_and_only_for_display() -> None:
    assert round_cents(D("2.675")) == D("2.68")
    assert round_cents(D("2.665")) == D("2.66")
    assert round_cents(D("0.125")) == D("0.12")
