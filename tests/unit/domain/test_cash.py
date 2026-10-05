"""Cash tracking (FR-TX-09): a month of activity whose broker balance is worked out by hand.

2 Jan  deposit 5000                                  cash 5000.00
3 Jan  buy 10 @ 100, fee 1 (cost 1001)               cash 3999.00
10 Jan dividend 12, withholding tax 1.80             cash 4009.20
15 Jan buy 5 @ 120, fee 1 (cost 601)                 cash 3408.20
20 Jan sell 6 @ 130, fee 1 (net 779)                 cash 4187.20
25 Jan custody fee 2.50                              cash 4184.70
28 Jan withdrawal 1000                               cash 3184.70
"""

from datetime import date
from decimal import Decimal

from folio.analytics.valuation import PricePoint, make_day_point, period_figures, value_holding
from folio.domain import TxIn, TxType, rebuild

D = Decimal


def tx(id: int, kind: TxType, day: int, **kw: object) -> TxIn:
    return TxIn(id=id, type=kind, trade_date=date(2024, 1, day), **kw)  # type: ignore[arg-type]


MONTH = [
    tx(1, TxType.DEPOSIT, 2, amount_eur=D("5000")),
    tx(2, TxType.BUY, 3, instrument_id=1, quantity=D(10), price=D(100), fees_eur=D(1)),
    tx(3, TxType.DIVIDEND, 10, instrument_id=1, amount_eur=D("12"), taxes_eur=D("1.80")),
    tx(4, TxType.BUY, 15, instrument_id=1, quantity=D(5), price=D(120), fees_eur=D(1)),
    tx(5, TxType.SELL, 20, instrument_id=1, quantity=D(6), price=D(130), fees_eur=D(1)),
    tx(6, TxType.FEE, 25, amount_eur=D("2.50")),
    tx(7, TxType.WITHDRAWAL, 28, amount_eur=D("1000")),
]


def test_cash_matches_the_broker_balance_after_a_month() -> None:
    state = rebuild(MONTH)
    assert state.cash_eur == D("3184.70")
    assert state.external_flows_eur == D("4000")  # deposits less withdrawals


def test_cash_after_each_step() -> None:
    expected = [
        D("5000"),
        D("3999"),
        D("4009.20"),
        D("3408.20"),
        D("4187.20"),
        D("4184.70"),
        D("3184.70"),
    ]
    for step, balance in enumerate(expected, start=1):
        assert rebuild(MONTH[:step]).cash_eur == balance


def test_transfers_move_holdings_without_cash() -> None:
    state = rebuild(
        [
            tx(
                1,
                TxType.TRANSFER_IN,
                2,
                instrument_id=1,
                quantity=D(5),
                price=D(10),
                amount_eur=D(60),
            ),
            tx(2, TxType.TRANSFER_OUT, 3, instrument_id=1, quantity=D(2)),
        ]
    )
    assert state.cash_eur == 0
    assert state.external_flows_eur == D("36")  # 60 in, 24 out: the holdings crossed the border


def test_the_result_is_the_same_whether_cash_is_tracked_or_not() -> None:
    state = rebuild(MONTH)
    price = PricePoint(date(2024, 1, 31), D(140), D(1))
    holding = value_holding(1, 1, D(9), state.positions[1].cost_basis_eur, price)  # 9 units: 1260

    # off: the same trades without deposits and withdrawals (an account that tracks no cash has
    # none), everything outside the holdings counted outside the value
    trades = rebuild(MONTH[1:6])
    assert trades.net_contributions_eur == D("823")  # 1001 + 601 - 779
    off = make_day_point(
        date(2024, 1, 31),
        [holding],
        trades.net_contributions_eur,
        trades.total_income_eur,
        trades.standalone_fees_eur + trades.taxes_eur,
    )
    # on: cash joins the value; contributions are the deposits less withdrawals
    on = make_day_point(
        date(2024, 1, 31),
        [holding],
        state.external_flows_eur,
        state.total_income_eur,
        state.standalone_fees_eur + state.taxes_eur,
        cash_eur=state.cash_eur,
        income_in_cash_eur=state.total_income_eur,
        costs_in_cash_eur=state.standalone_fees_eur + state.taxes_eur,
    )
    assert off.value_eur == D("1260")
    assert on.value_eur == D("4444.70")
    assert off.total_pnl_eur == D("444.70")  # 1260 - 823 + 12 - 4.30
    assert on.total_pnl_eur == D("444.70")  # 4444.70 - 4000
    assert (on.income_eur, on.costs_eur) == (D("12"), D("4.30"))  # still reported


def test_period_figures_do_not_count_cash_income_twice() -> None:
    start = make_day_point(date(2024, 1, 9), [], D("4000"), D(0), D(0), cash_eur=D("4000"))
    end = make_day_point(
        date(2024, 1, 10),
        [],
        D("4000"),
        D("12"),
        D("1.80"),
        cash_eur=D("4010.20"),
        income_in_cash_eur=D("12"),
        costs_in_cash_eur=D("1.80"),
    )
    figures = period_figures(start, end)
    assert figures.pnl_eur == D("10.20")  # the cash grew by exactly that
    assert (figures.income_eur, figures.costs_eur) == (D("12"), D("1.80"))
