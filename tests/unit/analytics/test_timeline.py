from datetime import date
from decimal import Decimal

from hypothesis import given

from folio.analytics.timeline import build_timeline
from folio.domain import CostBasisMethod, TxIn, TxType, rebuild, replay
from tests.unit.domain.test_ledger_properties import METHODS, PROPS, sequences

D = Decimal


def tx(id: int, kind: TxType, day: int, **kw: object) -> TxIn:
    return TxIn(id=id, type=kind, trade_date=date(2024, 1, day), **kw)  # type: ignore[arg-type]


BOOK = [
    tx(1, TxType.BUY, 2, instrument_id=1, quantity=D(10), price=D(100), fees_eur=D(1)),
    tx(2, TxType.BUY, 8, instrument_id=1, quantity=D(5), price=D(104)),
    tx(3, TxType.DIVIDEND, 10, instrument_id=1, amount_eur=D(3)),
    tx(4, TxType.SELL, 11, instrument_id=1, quantity=D(15), price=D(106), fees_eur=D(1)),
    tx(5, TxType.FEE, 12, amount_eur=D("2.50")),
]


def test_the_timeline_has_one_entry_per_trade_date_and_answers_any_day() -> None:
    timeline = build_timeline(BOOK, CostBasisMethod.FIFO)
    assert [d.day for d in timeline.days] == [2, 8, 10, 11, 12]
    assert timeline.at(date(2024, 1, 1)) is None  # before the first transaction
    mid = timeline.at(date(2024, 1, 9))  # between two dates: the one in force
    assert mid is not None and mid.day == date(2024, 1, 8)
    assert mid.positions[1].quantity == 15
    assert mid.net_contributions_eur == D("1001") + D("520")
    after = timeline.at(date(2024, 3, 1))
    assert after is not None and after.day == date(2024, 1, 12)


def test_a_sold_out_position_keeps_its_income_and_flows() -> None:
    timeline = build_timeline(BOOK, CostBasisMethod.FIFO)
    last = timeline.at(date(2024, 1, 12))
    assert last is not None
    gone = last.positions[1]
    assert gone.quantity == 0 and gone.cost_basis_eur == 0
    assert gone.income_eur == 3
    assert gone.net_invested_eur == D("1001") + D("520") - D("1589")  # 15 x 106 - 1
    assert last.costs_eur == D("2.50") and last.income_eur == 3


def test_entries_do_not_change_when_the_replay_moves_on() -> None:
    timeline = build_timeline(BOOK, CostBasisMethod.FIFO)
    first = timeline.entries[0]
    assert first.positions[1].quantity == 10  # not 0, although the position was later sold out


@PROPS
@given(sequences(), METHODS)
def test_replay_equals_rebuilding_up_to_each_date(txs: list[TxIn], method: CostBasisMethod) -> None:
    seen = 0
    for day, state in replay(txs, method):
        expected = rebuild([t for t in txs if t.trade_date <= day], method)
        assert state.net_contributions_eur == expected.net_contributions_eur
        assert state.cash_eur == expected.cash_eur
        assert state.external_flows_eur == expected.external_flows_eur
        assert state.total_income_eur == expected.total_income_eur
        assert state.taxes_eur == expected.taxes_eur
        for instrument_id, position in expected.positions.items():
            got = state.positions[instrument_id]
            assert got.quantity == position.quantity
            assert got.cost_basis_eur == position.cost_basis_eur
            assert got.net_invested_eur == position.net_invested_eur
            assert got.realized_pnl_eur == position.realized_pnl_eur
        seen += 1
    assert seen == len({t.trade_date for t in txs})
