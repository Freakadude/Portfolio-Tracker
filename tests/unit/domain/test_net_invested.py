from datetime import date
from decimal import Decimal

from folio.domain import TxIn, TxType, rebuild

D = Decimal


def tx(id: int, kind: TxType, day: int, **kw: object) -> TxIn:
    return TxIn(id=id, type=kind, trade_date=date(2024, 1, day), **kw)  # type: ignore[arg-type]


def test_net_invested_follows_buys_sells_and_transfers_per_position() -> None:
    state = rebuild(
        [
            tx(1, TxType.BUY, 1, instrument_id=1, quantity=D(10), price=D(100), fees_eur=D(1)),
            tx(2, TxType.SELL, 5, instrument_id=1, quantity=D(4), price=D(120)),
            tx(
                3,
                TxType.TRANSFER_IN,
                6,
                instrument_id=2,
                quantity=D(5),
                price=D(10),
                amount_eur=D(60),
            ),
            tx(4, TxType.TRANSFER_OUT, 7, instrument_id=2, quantity=D(2)),
            tx(5, TxType.DEPOSIT, 8, amount_eur=D(1000)),
        ]
    )
    # 1001 bought, 480 back from the sale; 60 carried in, 24 (2/5 of it) moved out
    assert state.positions[1].net_invested_eur == D("521")
    assert state.positions[2].net_invested_eur == D("36")
    # the account figure also holds deposits, which belong to no position
    assert state.net_contributions_eur == D("521") + D("36") + D("1000")
