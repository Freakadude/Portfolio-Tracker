import datetime as dt
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.db.models import Account
from folio.db.models_ledger import Instrument, LedgerTransaction, Listing
from folio.ledger_service import (
    TransactionChanges,
    TransactionError,
    TransactionIn,
    confirm_draft,
    create_batch,
    create_transaction,
    delete_transaction,
    preview_sell_transaction,
    update_transaction,
)
from folio.marketdata.fx import FxService, FxUnavailable, to_eur_multiplier
from folio.reports import reconcile

router = APIRouter(prefix="/transactions", tags=["transactions"])


class TransactionOut(BaseModel):
    id: int
    account_id: int
    account_name: str
    instrument_id: int | None
    instrument_name: str | None
    ticker: str | None
    type: str
    status: str
    trade_date: date
    settle_date: date | None
    quantity: Decimal
    price: Decimal
    currency: str
    fx_rate_to_eur: Decimal
    fees: Decimal
    fees_currency: str
    fees_fx_rate_to_eur: Decimal
    taxes: Decimal
    taxes_currency: str
    taxes_fx_rate_to_eur: Decimal
    net_amount_eur: Decimal | None
    ratio: Decimal | None
    note: str | None
    source: str
    external_ref: str | None
    import_batch_id: int | None


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    next_cursor: str | None


class MatchOut(BaseModel):
    lot_buy_transaction_id: int
    lot_trade_date: date | None
    quantity: Decimal
    cost_eur: Decimal
    proceeds_eur: Decimal
    realized_pnl_eur: Decimal


class SellPreviewOut(BaseModel):
    matches: list[MatchOut]
    net_proceeds_eur: Decimal
    cost_eur: Decimal
    realized_pnl_eur: Decimal
    realized_pct: Decimal | None
    remaining_quantity: Decimal
    remaining_cost_basis_eur: Decimal


class FxPrefillOut(BaseModel):
    currency: str
    date: dt.date
    rate_per_eur: Decimal
    rate_date: dt.date
    fx_rate_to_eur: Decimal


def _fail(exc: TransactionError) -> ApiError:
    errors = [{"field": field, "message": message} for field, message in exc.errors]
    status = 404 if "does not exist" in str(exc) and not errors else 422
    title = "Not found" if status == 404 else "Cannot save transaction"
    return ApiError(status, title, str(exc), errors=errors)


def transaction_out(db: Session, row: LedgerTransaction) -> TransactionOut:
    account = db.get(Account, row.account_id)
    instrument = db.get(Instrument, row.instrument_id) if row.instrument_id else None
    listing = None
    if instrument is not None:
        listing = db.scalars(
            select(Listing)
            .where(Listing.instrument_id == instrument.id)
            .order_by(Listing.pricing_primary.desc(), Listing.id)
            .limit(1)
        ).first()
    return TransactionOut(
        id=row.id,
        account_id=row.account_id,
        account_name=account.name if account else "",
        instrument_id=row.instrument_id,
        instrument_name=instrument.name if instrument else None,
        ticker=listing.ticker if listing else None,
        type=row.type,
        status=row.status,
        trade_date=row.trade_date,
        settle_date=row.settle_date,
        quantity=row.quantity,
        price=row.price,
        currency=row.currency,
        fx_rate_to_eur=row.fx_rate_to_eur,
        fees=row.fees,
        fees_currency=row.fees_currency,
        fees_fx_rate_to_eur=row.fees_fx_rate_to_eur,
        taxes=row.taxes,
        taxes_currency=row.taxes_currency,
        taxes_fx_rate_to_eur=row.taxes_fx_rate_to_eur,
        net_amount_eur=row.net_amount_eur,
        ratio=row.ratio,
        note=row.note,
        source=row.source,
        external_ref=row.external_ref,
        import_batch_id=row.import_batch_id,
    )


@router.get("", response_model=TransactionPage)
def list_transactions(
    _user: UserDep,
    db: DbDep,
    account: int | None = None,
    instrument: int | None = None,
    type: str | None = None,  # noqa: A002 - the query parameter is part of the public API
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    status: Annotated[str, Query(pattern="^(posted|draft|all)$")] = "posted",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    cursor: str | None = None,
) -> TransactionPage:
    query = select(LedgerTransaction).where(LedgerTransaction.deleted_at.is_(None))
    if account is not None:
        query = query.where(LedgerTransaction.account_id == account)
    if instrument is not None:
        query = query.where(LedgerTransaction.instrument_id == instrument)
    if type is not None:
        query = query.where(LedgerTransaction.type == type)
    if from_ is not None:
        query = query.where(LedgerTransaction.trade_date >= from_)
    if to is not None:
        query = query.where(LedgerTransaction.trade_date <= to)
    if status != "all":
        query = query.where(LedgerTransaction.status == status)
    if cursor:
        try:
            day_text, id_text = cursor.split(":")
            after_day, after_id = date.fromisoformat(day_text), int(id_text)
        except ValueError as exc:
            raise ApiError(422, "Invalid cursor", "The page cursor is not valid.") from exc
        query = query.where(
            or_(
                LedgerTransaction.trade_date < after_day,
                and_(LedgerTransaction.trade_date == after_day, LedgerTransaction.id < after_id),
            )
        )
    rows = list(
        db.scalars(
            query.order_by(LedgerTransaction.trade_date.desc(), LedgerTransaction.id.desc()).limit(
                limit + 1
            )
        )
    )
    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = f"{rows[-1].trade_date.isoformat()}:{rows[-1].id}" if more and rows else None
    return TransactionPage(items=[transaction_out(db, r) for r in rows], next_cursor=next_cursor)


@router.post("", response_model=TransactionOut, status_code=201)
def create(body: TransactionIn, _user: UserDep, db: DbDep) -> TransactionOut:
    try:
        row = create_transaction(db, body)
    except TransactionError as exc:
        raise _fail(exc) from exc
    return transaction_out(db, row)


class BatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transactions: list[TransactionIn] = Field(min_length=1, max_length=100)


class BatchOut(BaseModel):
    created: list[TransactionOut]


@router.post("/batch", response_model=BatchOut, status_code=201)
def create_many(body: BatchIn, _user: UserDep, db: DbDep) -> BatchOut:
    """Several transactions in one request, saved together or not at all (FR-TX-11): a bad row
    saves nothing and every problem is reported with its row number."""
    try:
        rows = create_batch(db, body.transactions)
    except TransactionError as exc:
        raise _fail(exc) from exc
    return BatchOut(created=[transaction_out(db, r) for r in rows])


class ReconcileRowIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument_id: int | None = None
    isin: str | None = Field(default=None, max_length=12)
    quantity: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def _identified(self) -> "ReconcileRowIn":
        if self.instrument_id is None and not self.isin:
            raise ValueError("Give the instrument or its ISIN for every row.")
        return self


class ReconcileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: int
    date: date
    rows: list[ReconcileRowIn] = Field(min_length=1, max_length=500)


class ReconcileLineOut(BaseModel):
    instrument_id: int | None
    name: str
    isin: str | None
    ours: Decimal
    broker: Decimal
    difference: Decimal  # broker minus ours
    status: str  # match | difference | missing_at_broker | unknown


class ReconcileOut(BaseModel):
    account_id: int
    date: date
    matches: int
    differences: int
    lines: list[ReconcileLineOut]


@router.post("/reconcile", response_model=ReconcileOut)
def reconcile_quantities(body: ReconcileIn, _user: UserDep, db: DbDep) -> ReconcileOut:
    """Compare the quantities your broker reports on a date with the ledger (FR-TX-10).
    Nothing is saved; the lines with a difference come first."""
    account = db.get(Account, body.account_id)
    if account is None or account.deleted_at is not None:
        raise ApiError(404, "Not found", "That account does not exist.")
    lines = reconcile(
        db, account, body.date, [(r.instrument_id, r.isin, r.quantity) for r in body.rows]
    )
    return ReconcileOut(
        account_id=account.id,
        date=body.date,
        matches=sum(1 for line in lines if line.status == "match"),
        differences=sum(1 for line in lines if line.status != "match"),
        lines=[
            ReconcileLineOut(
                instrument_id=line.instrument_id,
                name=line.name,
                isin=line.isin,
                ours=line.ours,
                broker=line.broker,
                difference=line.difference,
                status=line.status,
            )
            for line in lines
        ],
    )


@router.post("/preview-sell", response_model=SellPreviewOut)
def preview_sell(body: TransactionIn, _user: UserDep, db: DbDep) -> SellPreviewOut:
    """Shows the lots a sell would consume and the realized result before anything is saved."""
    try:
        result = preview_sell_transaction(db, body)
    except TransactionError as exc:
        raise _fail(exc) from exc
    dates = dict(
        db.execute(
            select(LedgerTransaction.id, LedgerTransaction.trade_date).where(
                LedgerTransaction.id.in_([m.lot_buy_tx_id for m in result.matches])
            )
        ).all()
    )
    return SellPreviewOut(
        matches=[
            MatchOut(
                lot_buy_transaction_id=m.lot_buy_tx_id,
                lot_trade_date=dates.get(m.lot_buy_tx_id),
                quantity=m.quantity,
                cost_eur=m.cost_eur,
                proceeds_eur=m.proceeds_eur,
                realized_pnl_eur=m.realized_pnl_eur,
            )
            for m in result.matches
        ],
        net_proceeds_eur=result.net_proceeds_eur,
        cost_eur=result.cost_eur,
        realized_pnl_eur=result.realized_pnl_eur,
        realized_pct=result.realized_pct,
        remaining_quantity=result.remaining_quantity,
        remaining_cost_basis_eur=result.remaining_cost_basis_eur,
    )


@router.get("/fx-prefill", response_model=FxPrefillOut)
def fx_prefill(
    currency: str, on: Annotated[date, Query(alias="date")], _user: UserDep, db: DbDep
) -> Any:
    """The ECB rate the form prefills for a trade date (the owner can overwrite it)."""
    code = currency.strip().upper()
    try:
        found = FxService(db).rate_per_eur(code, on)
    except FxUnavailable as exc:
        raise ApiError(422, "No exchange rate", str(exc)) from exc
    return FxPrefillOut(
        currency=code,
        date=on,
        rate_per_eur=found.rate_per_eur,
        rate_date=found.as_of,
        fx_rate_to_eur=to_eur_multiplier(found.rate_per_eur),
    )


@router.patch("/{transaction_id}", response_model=TransactionOut)
def update(
    transaction_id: int, body: TransactionChanges, _user: UserDep, db: DbDep
) -> TransactionOut:
    try:
        row = update_transaction(db, transaction_id, body)
    except TransactionError as exc:
        raise _fail(exc) from exc
    return transaction_out(db, row)


@router.post("/{transaction_id}/confirm", response_model=TransactionOut)
def confirm(
    transaction_id: int, _user: UserDep, db: DbDep, body: TransactionChanges | None = None
) -> TransactionOut:
    """Post a proposed (draft) transaction, optionally correcting it in the same step."""
    try:
        row = confirm_draft(db, transaction_id, body)
    except TransactionError as exc:
        raise _fail(exc) from exc
    return transaction_out(db, row)


@router.delete("/{transaction_id}", status_code=204)
def delete(transaction_id: int, _user: UserDep, db: DbDep) -> None:
    try:
        delete_transaction(db, transaction_id)
    except TransactionError as exc:
        raise _fail(exc) from exc
