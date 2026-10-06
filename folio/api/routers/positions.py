"""Positions and position detail. Ratio fields are fractions (0.05 means 5 percent)."""

import datetime as dt
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.api.routers.transactions import TransactionOut, transaction_out
from folio.db.models_ledger import Instrument, LedgerTransaction, LotMatch
from folio.domain import PositionState, position_metrics
from folio.domain.ledger import ZERO, precise
from folio.ledger_service import compute_state
from folio.positions import (
    PositionRow,
    PriceInfo,
    Totals,
    load_positions,
    merge_states,
    primary_listing,
    quote_for,
)

router = APIRouter(prefix="/positions", tags=["positions"])


class PriceOut(BaseModel):
    date: dt.date
    close: Decimal
    previous_close: Decimal | None
    source: str
    overridden: bool
    stale: bool
    delayed_price: Decimal | None  # a newer intraday quote, trading currency
    delayed_at: dt.datetime | None  # when it was quoted (UTC); label it "delayed"
    delayed_source: str | None


class PositionMetricsOut(BaseModel):
    quantity: Decimal
    avg_cost_eur: Decimal | None
    cost_basis_eur: Decimal
    market_value_eur: Decimal | None
    unrealized_pnl_eur: Decimal | None
    unrealized_ratio: Decimal | None
    realized_pnl_eur: Decimal
    income_eur: Decimal
    total_return_eur: Decimal | None
    total_return_ratio: Decimal | None
    day_change_eur: Decimal | None
    day_change_ratio: Decimal | None
    weight: Decimal | None
    market_value_native: Decimal | None
    cost_basis_native: Decimal
    unrealized_pnl_native: Decimal | None
    first_trade_date: dt.date | None
    price: PriceOut | None
    note: str | None


class PositionOut(PositionMetricsOut):
    account_id: int
    account_name: str
    instrument_id: int
    isin: str | None
    name: str
    ticker: str | None
    currency: str | None
    asset_class: str


class TotalsOut(BaseModel):
    positions: int
    unvalued_positions: int
    market_value_eur: Decimal
    cost_basis_eur: Decimal
    unrealized_pnl_eur: Decimal
    unrealized_ratio: Decimal | None
    realized_pnl_eur: Decimal
    income_eur: Decimal
    day_change_eur: Decimal | None


class PositionsOut(BaseModel):
    positions: list[PositionOut]
    totals: TotalsOut


class LotOut(BaseModel):
    buy_transaction_id: int
    account_id: int
    trade_date: dt.date
    open_quantity: Decimal
    cost_eur: Decimal
    avg_cost_eur: Decimal
    market_value_eur: Decimal | None
    unrealized_pnl_eur: Decimal | None
    unrealized_ratio: Decimal | None


class MatchOut(BaseModel):
    sell_transaction_id: int
    sell_date: dt.date | None
    lot_buy_transaction_id: int
    account_id: int
    quantity: Decimal
    cost_eur: Decimal
    proceeds_eur: Decimal
    realized_pnl_eur: Decimal


class InstrumentRef(BaseModel):
    id: int
    isin: str | None
    name: str
    asset_class: str
    ticker: str | None
    currency: str | None
    issuer: str | None
    product_url: str | None  # the issuer's page for this fund, saved by the owner


class PositionDetailOut(BaseModel):
    instrument: InstrumentRef
    account_id: int | None
    as_of: dt.date | None
    summary: PositionMetricsOut
    lots: list[LotOut]
    matches: list[MatchOut]
    transactions: list[TransactionOut]


def _price(info: PriceInfo | None) -> PriceOut | None:
    return (
        None
        if info is None
        else PriceOut(
            date=info.date,
            close=info.close,
            previous_close=info.previous_close,
            source=info.source,
            overridden=info.overridden,
            stale=info.stale,
            delayed_price=info.delayed_price,
            delayed_at=info.delayed_at,
            delayed_source=info.delayed_source,
        )
    )


def _metrics_out(
    state: PositionState,
    row_metrics: object | None,
    info: PriceInfo | None,
    weight: Decimal | None,
    note: str | None,
) -> PositionMetricsOut:
    m = row_metrics  # a PositionMetrics or None
    return PositionMetricsOut(
        quantity=state.quantity,
        avg_cost_eur=state.avg_cost_eur,
        cost_basis_eur=state.cost_basis_eur,
        market_value_eur=getattr(m, "market_value_eur", None),
        unrealized_pnl_eur=getattr(m, "unrealized_pnl_eur", None),
        unrealized_ratio=getattr(m, "unrealized_pct", None),
        realized_pnl_eur=state.realized_pnl_eur,
        income_eur=state.income_eur,
        total_return_eur=getattr(m, "total_return_eur", None),
        total_return_ratio=getattr(m, "total_return_pct", None),
        day_change_eur=getattr(m, "day_change_eur", None),
        day_change_ratio=getattr(m, "day_change_pct", None),
        weight=weight,
        market_value_native=getattr(m, "market_value_native", None),
        cost_basis_native=state.cost_basis_native,
        unrealized_pnl_native=getattr(m, "unrealized_pnl_native", None),
        first_trade_date=state.first_trade_date,
        price=_price(info),
        note=note,
    )


def _row_out(row: PositionRow) -> PositionOut:
    base = _metrics_out(row.state, row.metrics, row.price, row.weight, row.note)
    return PositionOut(
        **base.model_dump(),
        account_id=row.account.id,
        account_name=row.account.name,
        instrument_id=row.instrument.id,
        isin=row.instrument.isin,
        name=row.instrument.name,
        ticker=row.listing.ticker if row.listing else None,
        currency=row.listing.currency if row.listing else None,
        asset_class=row.instrument.asset_class,
    )


def _totals_out(t: Totals) -> TotalsOut:
    return TotalsOut(
        positions=t.positions,
        unvalued_positions=t.unvalued,
        market_value_eur=t.market_value_eur,
        cost_basis_eur=t.cost_basis_eur,
        unrealized_pnl_eur=t.unrealized_pnl_eur,
        unrealized_ratio=t.unrealized_pct,
        realized_pnl_eur=t.realized_pnl_eur,
        income_eur=t.income_eur,
        day_change_eur=t.day_change_eur,
    )


@router.get("", response_model=PositionsOut)
def list_positions(
    _user: UserDep,
    db: DbDep,
    account: int | None = None,
    as_of: date | None = None,
    include_closed: Annotated[bool, Query()] = False,
) -> PositionsOut:
    rows, totals = load_positions(
        db, account_id=account, as_of=as_of, include_closed=include_closed
    )
    return PositionsOut(positions=[_row_out(r) for r in rows], totals=_totals_out(totals))


def _matches(
    db: Session, rows: list[PositionRow], instrument_id: int, as_of: date | None
) -> list[MatchOut]:
    out: list[MatchOut] = []
    for row in rows:
        if as_of is None:
            found = db.scalars(
                select(LotMatch).where(
                    LotMatch.account_id == row.account.id, LotMatch.instrument_id == instrument_id
                )
            )
            matches = [
                (m.sell_transaction_id, m.lot_buy_transaction_id, m.quantity, m.cost_eur,
                 m.proceeds_eur, m.realized_pnl_eur)
                for m in found
            ]  # fmt: skip
        else:
            state = compute_state(db, row.account, as_of=as_of)
            matches = [
                (m.sell_tx_id, m.lot_buy_tx_id, m.quantity, m.cost_eur, m.proceeds_eur,
                 m.realized_pnl_eur)
                for m in state.matches
                if m.instrument_id == instrument_id
            ]  # fmt: skip
        for sell_id, buy_id, qty, cost, proceeds, pnl in matches:
            sell = db.get(LedgerTransaction, sell_id)
            out.append(
                MatchOut(
                    sell_transaction_id=sell_id,
                    sell_date=sell.trade_date if sell else None,
                    lot_buy_transaction_id=buy_id,
                    account_id=row.account.id,
                    quantity=qty,
                    cost_eur=cost,
                    proceeds_eur=proceeds,
                    realized_pnl_eur=pnl,
                )
            )
    return sorted(out, key=lambda m: (m.sell_date or date.min, m.sell_transaction_id))


@router.get("/{instrument_id}", response_model=PositionDetailOut)
def position_detail(
    instrument_id: int,
    _user: UserDep,
    db: DbDep,
    account: int | None = None,
    as_of: date | None = None,
) -> PositionDetailOut:
    instrument = db.get(Instrument, instrument_id)
    if instrument is None or instrument.deleted_at is not None:
        raise ApiError(404, "Not found", "That instrument does not exist.")
    today = date.today()
    all_rows, _ = load_positions(db, as_of=as_of, include_closed=True, today=today)
    rows = [
        r for r in all_rows
        if r.instrument.id == instrument_id and (account is None or r.account.id == account)
    ]  # fmt: skip
    listing = rows[0].listing if rows else None
    if not rows:
        # No position: still show the instrument's history (for example before the first buy)
        listing = primary_listing(db, instrument_id)
    merged = merge_states(instrument_id, [r.state for r in rows])
    quote, info, note = quote_for(db, instrument, listing, as_of or today, today)
    metrics = position_metrics(merged, quote) if quote is not None else None
    weight = sum((r.weight for r in rows if r.weight is not None), ZERO) if rows else None

    lots: list[LotOut] = []
    with precise():
        for row in rows:
            for lot in row.state.lots:
                value = (
                    lot.open_quantity * quote.price * quote.fx_rate if quote is not None else None
                )
                lots.append(
                    LotOut(
                        buy_transaction_id=lot.buy_tx_id,
                        account_id=row.account.id,
                        trade_date=lot.trade_date,
                        open_quantity=lot.open_quantity,
                        cost_eur=lot.cost_eur,
                        avg_cost_eur=lot.cost_eur / lot.open_quantity,
                        market_value_eur=value,
                        unrealized_pnl_eur=None if value is None else value - lot.cost_eur,
                        unrealized_ratio=(
                            None
                            if value is None or lot.cost_eur == 0
                            else (value - lot.cost_eur) / lot.cost_eur
                        ),
                    )
                )
    lots.sort(key=lambda lot: (lot.trade_date, lot.buy_transaction_id))

    history = select(LedgerTransaction).where(
        LedgerTransaction.instrument_id == instrument_id,
        LedgerTransaction.deleted_at.is_(None),
        LedgerTransaction.status == "posted",
    )
    if account is not None:
        history = history.where(LedgerTransaction.account_id == account)
    if as_of is not None:
        history = history.where(LedgerTransaction.trade_date <= as_of)
    transactions = list(
        db.scalars(
            history.order_by(
                LedgerTransaction.trade_date.desc(), LedgerTransaction.id.desc()
            ).limit(500)
        )
    )
    return PositionDetailOut(
        instrument=InstrumentRef(
            id=instrument.id,
            isin=instrument.isin,
            name=instrument.name,
            asset_class=instrument.asset_class,
            ticker=listing.ticker if listing else None,
            currency=listing.currency if listing else None,
            issuer=instrument.issuer,
            product_url=instrument.product_url,
        ),
        account_id=account,
        as_of=as_of,
        summary=_metrics_out(merged, metrics, info, weight, note),
        lots=lots,
        matches=_matches(db, rows, instrument_id, as_of),
        transactions=[transaction_out(db, t) for t in transactions],
    )
