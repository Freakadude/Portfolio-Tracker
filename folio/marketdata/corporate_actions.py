"""Corporate actions (FR-MD-07).

Splits found at a provider are *proposed*; confirming one adds a split transaction to every
account that held the instrument, which multiplies the open quantity and leaves the cost basis
untouched. Dividends of distributing funds and equities are proposed as *draft* transactions
(per-unit amount x units held before the ex-date, converted with the ECB rate); drafts never
reach the ledger until the owner confirms them, and deleting a draft dismisses it for good.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.audit import write_audit
from folio.db.base import utcnow
from folio.db.models import Account
from folio.db.models_ledger import CorporateAction, Instrument, LedgerTransaction, Listing
from folio.ledger_service import (
    TransactionError,
    TransactionIn,
    compute_state,
    insert_transaction,
    normalize,
    rebuild_account,
    request_snapshot_rebuild,
)
from folio.marketdata.base import ProviderError
from folio.marketdata.fallback import ProviderChain
from folio.marketdata.fx import FxService, FxUnavailable, to_eur_multiplier
from folio.marketdata.prices import listing_ref

DIVIDEND_MATCH_WINDOW = timedelta(days=45)  # a posted dividend this soon after ex-date counts
_CENT = Decimal("0.01")


class ActionError(ValueError):
    """The action cannot be applied; the message is for the owner."""


@dataclass
class Proposals:
    splits: int = 0
    dividends: int = 0
    notes: list[str] = field(default_factory=list)


def first_transaction_date(db: Session, instrument_id: int) -> date | None:
    rows = db.scalars(
        select(LedgerTransaction.trade_date)
        .where(
            LedgerTransaction.instrument_id == instrument_id,
            LedgerTransaction.deleted_at.is_(None),
            LedgerTransaction.status == "posted",
        )
        .order_by(LedgerTransaction.trade_date)
        .limit(1)
    )
    return next(iter(rows), None)


def held_instruments(db: Session) -> list[tuple[Instrument, Listing, date]]:
    """Active, provider-priced instruments the owner has ever had a transaction in."""
    out: list[tuple[Instrument, Listing, date]] = []
    query = (
        select(Instrument, Listing)
        .join(Listing, Listing.instrument_id == Instrument.id)
        .where(
            Listing.pricing_primary.is_(True),
            Instrument.status == "active",
            Instrument.deleted_at.is_(None),
            Instrument.manual.is_(False),
        )
        .order_by(Instrument.id)
    )
    for instrument, listing in db.execute(query):
        first = first_transaction_date(db, instrument.id)
        if first is not None:
            out.append((instrument, listing, first))
    return out


# --- splits -------------------------------------------------------------------------------------


def propose_splits(
    db: Session,
    chain: ProviderChain,
    instrument: Instrument,
    listing: Listing,
    first: date,
    today: date,
) -> int:
    result = chain.get_splits(listing_ref(listing, instrument.isin), first, today)
    added = 0
    for event in result.data:
        if event.ratio == 1:
            continue
        exists = db.scalar(
            select(CorporateAction.id).where(
                CorporateAction.instrument_id == instrument.id,
                CorporateAction.type == "split",
                CorporateAction.ex_date == event.ex_date,
            )
        )
        if exists is not None:  # also keeps a dismissed split dismissed
            continue
        db.add(
            CorporateAction(
                instrument_id=instrument.id,
                type="split",
                ex_date=event.ex_date,
                ratio=event.ratio,
                status="proposed",
                source=result.source,
            )
        )
        added += 1
    db.flush()
    return added


@dataclass(frozen=True)
class Holder:
    account: Account
    quantity: Decimal
    cost_basis_eur: Decimal


def holders_before(db: Session, instrument_id: int, ex_date: date) -> list[Holder]:
    """Accounts holding the instrument at the close before the ex-date."""
    holders: list[Holder] = []
    accounts = db.scalars(select(Account).where(Account.deleted_at.is_(None)).order_by(Account.id))
    for account in accounts:
        state = compute_state(db, account, as_of=ex_date - timedelta(days=1))
        position = state.positions.get(instrument_id)
        if position is not None and position.quantity > 0:
            holders.append(Holder(account, position.quantity, position.cost_basis_eur))
    return holders


def _action(db: Session, action_id: int) -> CorporateAction:
    action = db.get(CorporateAction, action_id)
    if action is None:
        raise ActionError("That corporate action does not exist.")
    return action


def confirm_split(db: Session, action_id: int, actor: str = "user") -> list[LedgerTransaction]:
    """Apply a proposed split: one split transaction per account that held the instrument."""
    action = _action(db, action_id)
    if action.type != "split" or action.ratio is None:
        raise ActionError("Only splits can be confirmed here.")
    if action.status != "proposed":
        raise ActionError(f"This split was already {action.status}.")
    created: list[LedgerTransaction] = []
    for holder in holders_before(db, action.instrument_id, action.ex_date):
        account = holder.account
        fields = normalize(
            db,
            TransactionIn(
                account_id=account.id,
                type="split",
                trade_date=action.ex_date,
                instrument_id=action.instrument_id,
                ratio=action.ratio,
                note=f"Split {action.ratio.normalize():f} new per 1 old (from {action.source}).",
            ),
        )
        created.append(
            insert_transaction(
                db,
                fields,
                source="corporate_action",
                external_ref=f"split:{action.instrument_id}:{action.ex_date.isoformat()}",
            )
        )
        try:
            rebuild_account(db, account)
        except ValueError as exc:  # a later sell no longer fits; refuse and keep nothing
            db.rollback()
            raise ActionError(f"The split cannot be applied to {account.name}: {exc}") from exc
    action.status = "applied"
    action.applied_at = utcnow()
    db.flush()
    write_audit(
        db,
        actor,
        "corporate_action",
        "confirm",
        entity_id=action.id,
        diff={
            "instrument_id": action.instrument_id,
            "ex_date": action.ex_date.isoformat(),
            "ratio": str(action.ratio),
            "transactions": [t.id for t in created],
        },
    )
    if created:
        request_snapshot_rebuild(db, action.ex_date)
    return created


def dismiss_action(db: Session, action_id: int, actor: str = "user") -> None:
    action = _action(db, action_id)
    if action.status != "proposed":
        raise ActionError(f"This action was already {action.status}.")
    action.status = "dismissed"
    db.flush()
    write_audit(db, actor, "corporate_action", "dismiss", entity_id=action.id,
                diff={"ex_date": action.ex_date.isoformat(), "type": action.type})  # fmt: skip


# --- dividends ----------------------------------------------------------------------------------


def _wants_dividends(instrument: Instrument) -> bool:
    return instrument.distribution == "DIST" or instrument.asset_class == "EQUITY"


def _has_posted_dividend(db: Session, account_id: int, instrument_id: int, ex_date: date) -> bool:
    found = db.scalar(
        select(LedgerTransaction.id)
        .where(
            LedgerTransaction.account_id == account_id,
            LedgerTransaction.instrument_id == instrument_id,
            LedgerTransaction.type == "dividend",
            LedgerTransaction.status == "posted",
            LedgerTransaction.deleted_at.is_(None),
            LedgerTransaction.trade_date >= ex_date,
            LedgerTransaction.trade_date <= ex_date + DIVIDEND_MATCH_WINDOW,
        )
        .limit(1)
    )
    return found is not None


def propose_dividends(
    db: Session, chain: ProviderChain, instrument: Instrument, listing: Listing, first: date,
    today: date, notes: list[str],
) -> int:  # fmt: skip
    if not _wants_dividends(instrument):
        return 0
    events = chain.get_dividends(listing_ref(listing, instrument.isin), first, today).data
    fx = FxService(db)
    added = 0
    for event in events:
        for holder in holders_before(db, instrument.id, event.ex_date):
            account, quantity = holder.account, holder.quantity
            ref = f"dividend:{instrument.id}:{event.ex_date.isoformat()}"
            seen = db.scalar(  # deleted rows count: deleting a draft dismisses it
                select(LedgerTransaction.id)
                .where(
                    LedgerTransaction.account_id == account.id,
                    LedgerTransaction.external_ref == ref,
                )
                .limit(1)
            )
            if seen is not None or _has_posted_dividend(
                db, account.id, instrument.id, event.ex_date
            ):
                continue
            currency = (event.currency or listing.currency).upper()
            try:
                rate = (
                    Decimal(1)
                    if currency == "EUR"
                    else to_eur_multiplier(fx.rate_per_eur(currency, event.ex_date).rate_per_eur)
                )
            except FxUnavailable as exc:
                notes.append(f"{instrument.name} {event.ex_date}: {exc}")
                continue
            gross = (event.amount * quantity * rate).quantize(_CENT, ROUND_HALF_EVEN)
            if gross <= 0:
                continue
            try:
                fields = normalize(
                    db,
                    TransactionIn(
                        account_id=account.id,
                        type="dividend",
                        trade_date=event.ex_date,
                        instrument_id=instrument.id,
                        net_amount_eur=gross,
                        note=(
                            f"Proposed: {event.amount.normalize():f} {currency} x "
                            f"{quantity.normalize():f} units. Dated at the ex-date; set the "
                            "payment date, the amount and any withholding tax to match your broker."
                        ),
                    ),
                    today=today,
                )
            except TransactionError as exc:
                notes.append(f"{instrument.name} {event.ex_date}: {exc}")
                continue
            draft = insert_transaction(
                db, fields, source="corporate_action", status="draft", external_ref=ref
            )
            write_audit(
                db,
                "worker",
                "transaction",
                "create",
                entity_id=draft.id,
                diff={
                    "type": "dividend",
                    "status": "draft",
                    "instrument_id": instrument.id,
                    "ex_date": event.ex_date.isoformat(),
                    "net_amount_eur": str(gross),
                },
            )
            added += 1
    db.flush()
    return added


def propose_all(db: Session, chain: ProviderChain, today: date) -> Proposals:
    """Fetch splits and dividends for everything the owner holds or has held. A provider
    failure for one instrument is noted and does not stop the others."""
    result = Proposals()
    for instrument, listing, first in held_instruments(db):
        try:
            result.splits += propose_splits(db, chain, instrument, listing, first, today)
            result.dividends += propose_dividends(
                db, chain, instrument, listing, first, today, result.notes
            )
        except ProviderError as exc:
            result.notes.append(f"{instrument.name}: {exc}")
    return result
