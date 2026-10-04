"""Recording transactions and keeping the derived tables (lots, matches, positions) in step.

Transactions are the only source of truth. Every create, edit or delete is validated, audited,
and followed by a rebuild of that account's derived tables through the pure domain code
(`folio.domain.ledger.rebuild`). A change that would make a sell exceed the holding is rejected
with a plain message and nothing is saved (invariant 3).
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from folio.audit import write_audit
from folio.db.base import utcnow
from folio.db.models import Account
from folio.db.models_ledger import (
    Instrument,
    LedgerTransaction,
    Listing,
    Lot,
    LotMatch,
    Position,
)
from folio.domain import (
    CostBasisMethod,
    LedgerError,
    LedgerState,
    SellPreview,
    TxIn,
    TxType,
    preview_sell,
    rebuild,
)
from folio.jobs.requests import enqueue
from folio.marketdata.fx import FxService, FxUnavailable

TransactionType = Literal[
    "buy",
    "sell",
    "dividend",
    "interest",
    "fee",
    "tax",
    "split",
    "transfer_in",
    "transfer_out",
    "deposit",
    "withdrawal",
]
_TRADES = {"buy", "sell"}
_TRANSFERS = {"transfer_in", "transfer_out"}
_CASH_AMOUNT = {"dividend", "interest", "fee", "tax", "deposit", "withdrawal"}
_CURRENCY = re.compile(r"^[A-Z]{3}$")
ZERO = Decimal(0)


class TransactionError(ValueError):
    """The input cannot be saved; `errors` lists what to fix, in plain language."""

    def __init__(self, message: str, errors: list[tuple[str, str]] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


class TransactionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: int
    type: TransactionType
    trade_date: date
    instrument_id: int | None = None
    settle_date: date | None = None
    quantity: Decimal | None = None
    price: Decimal | None = Field(default=None, ge=0)
    currency: str | None = None
    fx_rate_to_eur: Decimal | None = Field(default=None, gt=0)
    fees: Decimal = Field(default=ZERO, ge=0)
    fees_currency: str | None = None
    fees_fx_rate_to_eur: Decimal | None = Field(default=None, gt=0)
    taxes: Decimal = Field(default=ZERO, ge=0)
    taxes_currency: str | None = None
    taxes_fx_rate_to_eur: Decimal | None = Field(default=None, gt=0)
    net_amount_eur: Decimal | None = None  # EUR amount for income, costs and cash flows
    ratio: Decimal | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=2000)


class TransactionChanges(BaseModel):
    """Any subset of the input fields; the merged result is validated again."""

    model_config = ConfigDict(extra="forbid")

    trade_date: date | None = None
    instrument_id: int | None = None
    settle_date: date | None = None
    quantity: Decimal | None = None
    price: Decimal | None = Field(default=None, ge=0)
    currency: str | None = None
    fx_rate_to_eur: Decimal | None = Field(default=None, gt=0)
    fees: Decimal | None = Field(default=None, ge=0)
    fees_currency: str | None = None
    fees_fx_rate_to_eur: Decimal | None = Field(default=None, gt=0)
    taxes: Decimal | None = Field(default=None, ge=0)
    taxes_currency: str | None = None
    taxes_fx_rate_to_eur: Decimal | None = Field(default=None, gt=0)
    net_amount_eur: Decimal | None = None
    ratio: Decimal | None = Field(default=None, gt=0)
    note: str | None = None


_INPUT_FIELDS = tuple(TransactionIn.model_fields)


def to_txin(row: LedgerTransaction) -> TxIn:
    """A stored row as the domain sees it: everything converted to EUR."""
    kind = TxType(row.type)
    return TxIn(
        id=row.id,
        type=kind,
        trade_date=row.trade_date,
        instrument_id=row.instrument_id,
        quantity=row.quantity,
        price=row.price,
        fx_rate=row.fx_rate_to_eur,
        fees_eur=row.fees * row.fees_fx_rate_to_eur,
        taxes_eur=row.taxes * row.taxes_fx_rate_to_eur,
        amount_eur=row.net_amount_eur if row.type not in _TRADES else None,
        ratio=row.ratio,
    )


def fields_to_txin(tx_id: int, fields: dict[str, Any]) -> TxIn:
    """The same conversion as `to_txin`, for normalised fields that are not saved yet."""
    kind = TxType(fields["type"])
    return TxIn(
        id=tx_id,
        type=kind,
        trade_date=fields["trade_date"],
        instrument_id=fields["instrument_id"],
        quantity=fields["quantity"],
        price=fields["price"],
        fx_rate=fields["fx_rate_to_eur"],
        fees_eur=fields["fees"] * fields["fees_fx_rate_to_eur"],
        taxes_eur=fields["taxes"] * fields["taxes_fx_rate_to_eur"],
        amount_eur=fields["net_amount_eur"] if fields["type"] not in _TRADES else None,
        ratio=fields["ratio"],
    )


def _account(db: Session, account_id: int) -> Account:
    account = db.get(Account, account_id)
    if account is None or account.deleted_at is not None:
        raise TransactionError("That account does not exist.")
    return account


def _snapshot(row: LedgerTransaction) -> dict[str, Any]:
    out: dict[str, Any] = {"account_id": row.account_id, "status": row.status}
    for key in _INPUT_FIELDS:
        if key == "account_id":
            continue
        value = getattr(row, key if key != "currency" else "currency")
        out[key] = (
            value.isoformat()
            if isinstance(value, date)
            else (str(value) if isinstance(value, Decimal) else value)
        )
    return out


# --- validation and normalisation ---------------------------------------------------------------


def _check_currency(code: str | None, field: str, errors: list[tuple[str, str]]) -> str | None:
    if code is None:
        return None
    code = code.strip().upper()
    if not _CURRENCY.match(code):
        errors.append((field, "A currency is a three-letter code such as EUR or USD."))
    return code


def _rate(
    fx: FxService,
    currency: str,
    on: date,
    given: Decimal | None,
    field: str,
    errors: list[tuple[str, str]],
) -> Decimal:
    """The owner's rate if given, otherwise the ECB rate prefilled for that day (FR-TX-02)."""
    if currency == "EUR":
        return Decimal(1)
    if given is not None:
        return given
    try:
        return fx.multiplier(currency, on)
    except FxUnavailable as exc:
        errors.append((field, f"{exc} You can also enter the exchange rate yourself."))
        return Decimal(1)


def normalize(db: Session, data: TransactionIn, today: date | None = None) -> dict[str, Any]:
    """Validate one transaction for its type and return the row fields (rates filled in)."""
    errors: list[tuple[str, str]] = []
    today = today or date.today()
    kind = data.type

    account = db.get(Account, data.account_id)
    if account is None or account.deleted_at is not None:
        errors.append(("account_id", "That account does not exist."))
    if data.trade_date > today:
        errors.append(("trade_date", "A trade date cannot be in the future."))
    if data.settle_date and data.settle_date < data.trade_date:
        errors.append(("settle_date", "Settlement cannot be before the trade date."))

    instrument = None
    if data.instrument_id is not None:
        instrument = db.get(Instrument, data.instrument_id)
        if instrument is None or instrument.deleted_at is not None:
            errors.append(("instrument_id", "That instrument does not exist."))
    needs_instrument = kind in _TRADES | _TRANSFERS | {"split", "dividend"}
    if needs_instrument and data.instrument_id is None:
        errors.append(("instrument_id", f"A {kind.replace('_', ' ')} needs an instrument."))

    quantity = data.quantity
    if kind in _TRADES | _TRANSFERS and (quantity is None or quantity <= 0):
        errors.append(("quantity", "The quantity must be greater than zero."))
    if kind in _TRADES and data.price is None:
        errors.append(("price", "A trade needs a price (it can be zero for a gift)."))
    if kind == "split" and data.ratio is None:
        errors.append(("ratio", "A split needs a ratio, for example 4 for a 1-for-4 split."))
    if kind in _CASH_AMOUNT and (data.net_amount_eur is None or data.net_amount_eur <= 0):
        errors.append(("net_amount_eur", "Enter the amount in euros, greater than zero."))

    currency = _check_currency(data.currency, "currency", errors)
    fees_currency = _check_currency(data.fees_currency, "fees_currency", errors) or "EUR"
    taxes_currency = _check_currency(data.taxes_currency, "taxes_currency", errors) or "EUR"
    if kind in _TRADES | _TRANSFERS and currency is None and instrument is not None:
        listing = db.scalars(
            select(Listing)
            .where(Listing.instrument_id == instrument.id)
            .order_by(Listing.pricing_primary.desc(), Listing.id)
            .limit(1)
        ).first()
        currency = listing.currency if listing else "EUR"
    currency = currency or "EUR"

    fx = FxService(db)
    fx_rate = _rate(fx, currency, data.trade_date, data.fx_rate_to_eur, "fx_rate_to_eur", errors)
    fees_rate = _rate(
        fx, fees_currency, data.trade_date, data.fees_fx_rate_to_eur, "fees_fx_rate_to_eur", errors
    )
    taxes_rate = _rate(
        fx,
        taxes_currency,
        data.trade_date,
        data.taxes_fx_rate_to_eur,
        "taxes_fx_rate_to_eur",
        errors,
    )

    if errors:
        raise TransactionError("Some fields need attention.", errors)

    qty = quantity if kind in _TRADES | _TRANSFERS else ZERO
    price = data.price if data.price is not None else ZERO
    net_amount = data.net_amount_eur
    if kind in _TRADES:
        # The cash effect in EUR, so the figure can be compared with the broker statement.
        gross = (qty or ZERO) * price * fx_rate
        costs = data.fees * fees_rate + data.taxes * taxes_rate
        net_amount = -(gross + costs) if kind == "buy" else gross - costs
    return {
        "account_id": data.account_id,
        "instrument_id": data.instrument_id,
        "type": kind,
        "trade_date": data.trade_date,
        "settle_date": data.settle_date,
        "quantity": qty or ZERO,
        "price": price,
        "currency": currency,
        "fx_rate_to_eur": fx_rate,
        "fees": data.fees,
        "fees_currency": fees_currency,
        "fees_fx_rate_to_eur": fees_rate,
        "taxes": data.taxes,
        "taxes_currency": taxes_currency,
        "taxes_fx_rate_to_eur": taxes_rate,
        "net_amount_eur": net_amount,
        "ratio": data.ratio,
        "note": data.note,
    }


# --- derived tables -----------------------------------------------------------------------------


def account_transactions(
    db: Session, account_id: int, *, posted_only: bool = True
) -> list[LedgerTransaction]:
    query = select(LedgerTransaction).where(
        LedgerTransaction.account_id == account_id, LedgerTransaction.deleted_at.is_(None)
    )
    if posted_only:
        query = query.where(LedgerTransaction.status == "posted")
    return list(db.scalars(query.order_by(LedgerTransaction.trade_date, LedgerTransaction.id)))


def compute_state(db: Session, account: Account, *, as_of: date | None = None) -> LedgerState:
    rows = account_transactions(db, account.id)
    if as_of is not None:
        rows = [r for r in rows if r.trade_date <= as_of]
    return rebuild((to_txin(r) for r in rows), CostBasisMethod(account.cost_basis_method))


def rebuild_account(db: Session, account: Account) -> LedgerState:
    """Recompute lots, lot matches and positions for an account from its transactions
    (invariant 5: running it twice gives identical rows). Raises LedgerError, for example when
    a sell would exceed the holding, in which case nothing has been written."""
    state = compute_state(db, account)  # may raise before any row is touched
    db.execute(delete(LotMatch).where(LotMatch.account_id == account.id))
    db.execute(delete(Lot).where(Lot.account_id == account.id))
    db.execute(delete(Position).where(Position.account_id == account.id))
    for pos in state.positions.values():
        for lot in pos.lots:
            db.add(
                Lot(
                    account_id=account.id,
                    instrument_id=pos.instrument_id,
                    buy_transaction_id=lot.buy_tx_id,
                    trade_date=lot.trade_date,
                    open_quantity=lot.open_quantity,
                    cost_eur=lot.cost_eur,
                    cost_native=lot.cost_native,
                )
            )
        db.add(
            Position(
                account_id=account.id,
                instrument_id=pos.instrument_id,
                quantity=pos.quantity,
                cost_basis_eur=pos.cost_basis_eur,
                cost_basis_native=pos.cost_basis_native,
                avg_cost_eur=pos.avg_cost_eur,
                realized_pnl_eur=pos.realized_pnl_eur,
                income_eur=pos.income_eur,
                invested_eur=pos.invested_eur,
                proceeds_eur=pos.proceeds_eur,
                first_trade_date=pos.first_trade_date,
            )
        )
    for match in state.matches:
        db.add(
            LotMatch(
                account_id=account.id,
                instrument_id=match.instrument_id,
                sell_transaction_id=match.sell_tx_id,
                lot_buy_transaction_id=match.lot_buy_tx_id,
                quantity=match.quantity,
                cost_eur=match.cost_eur,
                proceeds_eur=match.proceeds_eur,
                realized_pnl_eur=match.realized_pnl_eur,
            )
        )
    db.flush()
    return state


def _rebuild_or_reject(db: Session, account: Account) -> None:
    try:
        rebuild_account(db, account)
    except LedgerError as exc:
        db.rollback()  # nothing from this change is kept
        raise TransactionError(str(exc), [("quantity", str(exc))]) from exc


def request_snapshot_rebuild(db: Session, from_date: date) -> None:
    """Portfolio snapshots from this date forward are stale (FR-TX-06); the worker redoes them."""
    enqueue(db, "snapshots", {"from": from_date.isoformat()})


# --- create, update, delete ----------------------------------------------------------------------


def insert_transaction(
    db: Session,
    fields: dict[str, Any],
    *,
    source: str = "manual",
    status: str = "posted",
    external_ref: str | None = None,
    import_batch_id: int | None = None,
) -> LedgerTransaction:
    row = LedgerTransaction(
        **fields,
        source=source,
        status=status,
        external_ref=external_ref,
        import_batch_id=import_batch_id,
    )
    db.add(row)
    db.flush()
    return row


def create_transaction(db: Session, data: TransactionIn, actor: str = "user") -> LedgerTransaction:
    fields = normalize(db, data)
    account = _account(db, data.account_id)
    row = insert_transaction(db, fields)
    _rebuild_or_reject(db, account)
    write_audit(db, actor, "transaction", "create", entity_id=row.id, diff=_snapshot(row))
    request_snapshot_rebuild(db, row.trade_date)
    return row


def _live(db: Session, transaction_id: int) -> LedgerTransaction:
    row = db.get(LedgerTransaction, transaction_id)
    if row is None or row.deleted_at is not None:
        raise TransactionError("That transaction does not exist.")
    return row


def _as_input(row: LedgerTransaction) -> dict[str, Any]:
    values = {key: getattr(row, key) for key in _INPUT_FIELDS}
    return values


def update_transaction(
    db: Session, transaction_id: int, changes: TransactionChanges, actor: str = "user"
) -> LedgerTransaction:
    row = _live(db, transaction_id)
    before = _snapshot(row)
    old_date = row.trade_date
    merged = _as_input(row)
    given = changes.model_dump(exclude_unset=True)
    merged.update(given)
    # A new currency invalidates the stored rate. A new date does too, unless the owner had
    # overridden the ECB rate (then their broker's rate is kept): a stored rate equal to the
    # ECB prefill for the old date was never overridden.
    fx = FxService(db)
    for currency_key, rate_key in (
        ("currency", "fx_rate_to_eur"),
        ("fees_currency", "fees_fx_rate_to_eur"),
        ("taxes_currency", "taxes_fx_rate_to_eur"),
    ):
        if rate_key in given:
            continue
        if (
            currency_key in given
            or "trade_date" in given
            and _is_ecb_prefill(fx, getattr(row, currency_key), old_date, getattr(row, rate_key))
        ):
            merged[rate_key] = None
    fields = normalize(db, TransactionIn.model_validate(merged))
    account = _account(db, row.account_id)
    for key, value in fields.items():
        setattr(row, key, value)
    db.flush()
    _rebuild_or_reject(db, account)
    after = _snapshot(row)
    diff = {k: {"old": before[k], "new": after[k]} for k in after if before[k] != after[k]}
    if diff:
        write_audit(db, actor, "transaction", "update", entity_id=row.id, diff=diff)
    request_snapshot_rebuild(db, min(old_date, row.trade_date))
    return row


def _is_ecb_prefill(fx: FxService, currency: str, on: date, stored: Decimal) -> bool:
    if currency == "EUR":
        return False
    try:
        return bool(fx.multiplier(currency, on) == stored)
    except FxUnavailable:
        return False


def delete_transaction(db: Session, transaction_id: int, actor: str = "user") -> None:
    row = _live(db, transaction_id)
    account = _account(db, row.account_id)
    snapshot = _snapshot(row)
    row.deleted_at = utcnow()
    db.flush()
    _rebuild_or_reject(db, account)  # deleting a buy that a later sell relies on is refused
    write_audit(db, actor, "transaction", "delete", entity_id=row.id, diff=snapshot)
    request_snapshot_rebuild(db, row.trade_date)


def rebuild_after_bulk(
    db: Session, account: Account, earliest: date | None, actor: str = "user"
) -> None:
    """For bulk inserts such as imports: one rebuild and one snapshot request for the batch."""
    _rebuild_or_reject(db, account)
    if earliest is not None:
        request_snapshot_rebuild(db, earliest)


def change_cost_basis_method(
    db: Session, account: Account, method: CostBasisMethod, actor: str = "user"
) -> None:
    """Switch FIFO and average cost; every derived number is recomputed and the change audited."""
    old = account.cost_basis_method
    if old == method.value:
        return
    account.cost_basis_method = method.value
    db.flush()
    _rebuild_or_reject(db, account)
    write_audit(
        db,
        actor,
        "account",
        "cost_basis_method",
        entity_id=account.id,
        diff={"cost_basis_method": {"old": old, "new": method.value}},
    )
    first = db.scalar(
        select(func.min(LedgerTransaction.trade_date)).where(
            LedgerTransaction.account_id == account.id, LedgerTransaction.deleted_at.is_(None)
        )
    )
    if first is not None:
        request_snapshot_rebuild(db, first)


# --- sell preview --------------------------------------------------------------------------------


def preview_sell_transaction(db: Session, data: TransactionIn) -> SellPreview:
    """What saving this sell would do, computed through the same code path as the ledger
    (FR-TX-04). Nothing is written."""
    if data.type != "sell":
        raise TransactionError("Only a sell can be previewed.")
    fields = normalize(db, data)
    account = _account(db, data.account_id)
    history = [to_txin(r) for r in account_transactions(db, account.id)]
    candidate = TxIn(
        id=-1,
        type=TxType.SELL,
        trade_date=fields["trade_date"],
        instrument_id=fields["instrument_id"],
        quantity=fields["quantity"],
        price=fields["price"],
        fx_rate=fields["fx_rate_to_eur"],
        fees_eur=fields["fees"] * fields["fees_fx_rate_to_eur"],
        taxes_eur=fields["taxes"] * fields["taxes_fx_rate_to_eur"],
    )
    try:
        return preview_sell(history, candidate, CostBasisMethod(account.cost_basis_method))
    except LedgerError as exc:
        raise TransactionError(str(exc), [("quantity", str(exc))]) from exc
