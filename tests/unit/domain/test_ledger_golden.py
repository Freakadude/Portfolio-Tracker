from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from folio.domain import CostBasisMethod, OversellError, TxIn, TxType, preview_sell, rebuild
from folio.domain.ledger import precise

FIXTURES = yaml.safe_load(
    (Path(__file__).resolve().parents[2] / "fixtures" / "ledger" / "scenarios.yaml").read_text(
        encoding="utf-8"
    )
)


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def tx_from_yaml(raw: dict[str, Any]) -> TxIn:
    return TxIn(
        id=raw["id"],
        type=TxType(raw["type"]),
        trade_date=raw["date"],
        instrument_id=raw.get("instrument"),
        quantity=_dec(raw.get("quantity", 0)),
        price=_dec(raw.get("price", 0)),
        fx_rate=_dec(raw.get("fx", 1)),
        fees_eur=_dec(raw.get("fees", 0)),
        taxes_eur=_dec(raw.get("taxes", 0)),
        amount_eur=_dec(raw["amount"]) if "amount" in raw else None,
        ratio=_dec(raw["ratio"]) if "ratio" in raw else None,
    )


CASES = [
    pytest.param(s, method, id=f"{s['name']}-{method}")
    for s in FIXTURES
    for method in ("FIFO", "AVG")
]


@pytest.mark.parametrize(("scenario", "method"), CASES)
def test_golden_scenarios(scenario: dict[str, Any], method: str) -> None:
    txs = [tx_from_yaml(t) for t in scenario["txs"]]
    state = rebuild(txs, CostBasisMethod(method))
    expected = scenario["expected"][method]
    pos = state.position(1)
    assert pos.quantity == _dec(expected["quantity"])
    assert pos.cost_basis_eur == _dec(expected["cost_basis"])
    assert pos.realized_pnl_eur == _dec(expected["realized"])
    assert state.net_contributions_eur == _dec(expected["net_contributions"])
    assert state.total_income_eur == _dec(expected.get("income", 0))
    assert state.standalone_fees_eur == _dec(expected.get("fees", 0))
    assert state.taxes_eur == _dec(expected.get("taxes", 0))


def test_matches_explain_every_realized_number() -> None:
    scenario = FIXTURES[0]  # fifo_vs_avg_with_fees
    state = rebuild([tx_from_yaml(t) for t in scenario["txs"]], CostBasisMethod.FIFO)
    assert [(m.lot_buy_tx_id, m.quantity, m.cost_eur) for m in state.matches] == [
        (1, Decimal(10), Decimal("1001")),
        (2, Decimal(5), Decimal("600.5")),
    ]
    assert sum(m.realized_pnl_eur for m in state.matches) == Decimal("346.5")
    assert sum(m.proceeds_eur for m in state.matches) == Decimal(1948)  # split without drift


def test_average_cost_keeps_a_single_pooled_lot() -> None:
    scenario = FIXTURES[0]
    state = rebuild([tx_from_yaml(t) for t in scenario["txs"]], CostBasisMethod.AVG)
    assert len(state.position(1).lots) == 1
    assert [m.quantity for m in state.matches] == [Decimal(15)]


def test_switching_method_changes_realized_but_not_total_cost() -> None:
    txs = [tx_from_yaml(t) for t in FIXTURES[0]["txs"]]
    fifo, avg = rebuild(txs, CostBasisMethod.FIFO), rebuild(txs, CostBasisMethod.AVG)
    assert fifo.position(1).realized_pnl_eur != avg.position(1).realized_pnl_eur
    for state in (fifo, avg):
        pos = state.position(1)
        assert pos.cost_basis_eur + sum(m.cost_eur for m in state.matches) == pos.invested_eur


def test_oversell_is_rejected_with_a_clear_message() -> None:
    txs = [tx_from_yaml(t) for t in FIXTURES[0]["txs"]]
    too_big = TxIn(
        99, TxType.SELL, date(2024, 4, 1), instrument_id=1, quantity=Decimal(6), price=Decimal(1)
    )
    with pytest.raises(OversellError, match=r"Cannot sell 6 units on 2024-04-01: only 5 are held"):
        rebuild([*txs, too_big])


def test_selling_something_never_held_is_rejected() -> None:
    sell = TxIn(1, TxType.SELL, date(2024, 1, 1), instrument_id=7, quantity=Decimal(1))
    with pytest.raises(OversellError):
        rebuild([sell])


def test_preview_matches_what_saving_produces() -> None:
    txs = [tx_from_yaml(t) for t in FIXTURES[0]["txs"]]
    new_sell = TxIn(
        10,
        TxType.SELL,
        date(2024, 5, 1),
        instrument_id=1,
        quantity=Decimal(3),
        price=Decimal("140"),
        fees_eur=Decimal("1.5"),
    )
    preview = preview_sell(txs, new_sell)
    saved = rebuild([*txs, new_sell])
    assert preview.matches == tuple(m for m in saved.matches if m.sell_tx_id == 10)
    assert preview.realized_pnl_eur == sum(m.realized_pnl_eur for m in preview.matches)
    assert preview.remaining_quantity == saved.position(1).quantity == Decimal(2)
    assert preview.remaining_cost_basis_eur == saved.position(1).cost_basis_eur
    with precise():
        assert preview.realized_pct == preview.realized_pnl_eur / preview.cost_eur


def test_preview_of_an_oversell_raises() -> None:
    txs = [tx_from_yaml(t) for t in FIXTURES[0]["txs"]]
    big = TxIn(10, TxType.SELL, date(2024, 5, 1), instrument_id=1, quantity=Decimal(50))
    with pytest.raises(OversellError):
        preview_sell(txs, big)


@pytest.mark.parametrize(
    "bad",
    [
        TxIn(1, TxType.BUY, date(2024, 1, 1), instrument_id=1, quantity=Decimal(0)),
        TxIn(1, TxType.BUY, date(2024, 1, 1), quantity=Decimal(1)),
        TxIn(1, TxType.SPLIT, date(2024, 1, 1), instrument_id=1),
        TxIn(1, TxType.DIVIDEND, date(2024, 1, 1), amount_eur=Decimal(5)),
        TxIn(1, TxType.DEPOSIT, date(2024, 1, 1)),
    ],
)
def test_invalid_transactions_are_explained(bad: TxIn) -> None:
    from folio.domain import LedgerError

    with pytest.raises(LedgerError):
        rebuild([bad])
