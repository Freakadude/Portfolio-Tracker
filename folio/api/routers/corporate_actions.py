import datetime as dt
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.db.models_ledger import CorporateAction, Instrument, Listing
from folio.marketdata.corporate_actions import (
    ActionError,
    confirm_split,
    dismiss_action,
    holders_before,
)

router = APIRouter(prefix="/corporate-actions", tags=["corporate actions"])


class EffectOut(BaseModel):
    account_id: int
    account_name: str
    quantity_before: Decimal
    quantity_after: Decimal
    cost_basis_eur: Decimal  # unchanged by a split


class ActionOut(BaseModel):
    id: int
    instrument_id: int
    instrument_name: str
    isin: str | None
    ticker: str | None
    type: str
    ex_date: dt.date
    ratio: Decimal | None
    status: str
    source: str | None
    applied_at: dt.datetime | None
    effects: list[EffectOut]
    transaction_ids: list[int]


def _out(
    db: Session, action: CorporateAction, transaction_ids: list[int] | None = None
) -> ActionOut:
    instrument = db.get(Instrument, action.instrument_id)
    listing = db.scalars(
        select(Listing)
        .where(Listing.instrument_id == action.instrument_id)
        .order_by(Listing.pricing_primary.desc(), Listing.id)
        .limit(1)
    ).first()
    effects: list[EffectOut] = []
    if action.status == "proposed" and action.type == "split" and action.ratio is not None:
        for holder in holders_before(db, action.instrument_id, action.ex_date):
            effects.append(
                EffectOut(
                    account_id=holder.account.id,
                    account_name=holder.account.name,
                    quantity_before=holder.quantity,
                    quantity_after=holder.quantity * action.ratio,
                    cost_basis_eur=holder.cost_basis_eur,
                )
            )
    return ActionOut(
        id=action.id,
        instrument_id=action.instrument_id,
        instrument_name=instrument.name if instrument else "",
        isin=instrument.isin if instrument else None,
        ticker=listing.ticker if listing else None,
        type=action.type,
        ex_date=action.ex_date,
        ratio=action.ratio,
        status=action.status,
        source=action.source,
        applied_at=action.applied_at,
        effects=effects,
        transaction_ids=transaction_ids or [],
    )


@router.get("", response_model=list[ActionOut])
def list_actions(
    _user: UserDep,
    db: DbDep,
    status: Annotated[str, Query(pattern="^(proposed|applied|dismissed|all)$")] = "proposed",
) -> list[ActionOut]:
    query = select(CorporateAction).order_by(CorporateAction.ex_date.desc(), CorporateAction.id)
    if status != "all":
        query = query.where(CorporateAction.status == status)
    return [_out(db, a) for a in db.scalars(query)]


def _find(db: Session, action_id: int) -> CorporateAction:
    action = db.get(CorporateAction, action_id)
    if action is None:
        raise ApiError(404, "Not found", "That corporate action does not exist.")
    return action


@router.post("/{action_id}/confirm", response_model=ActionOut)
def confirm(action_id: int, _user: UserDep, db: DbDep) -> ActionOut:
    """Apply a proposed split to every account that held the instrument."""
    action = _find(db, action_id)
    try:
        created = confirm_split(db, action_id)
    except ActionError as exc:
        raise ApiError(409, "Cannot apply", str(exc)) from exc
    return _out(db, action, [t.id for t in created])


@router.post("/{action_id}/dismiss", response_model=ActionOut)
def dismiss(action_id: int, _user: UserDep, db: DbDep) -> ActionOut:
    action = _find(db, action_id)
    try:
        dismiss_action(db, action_id)
    except ActionError as exc:
        raise ApiError(409, "Cannot dismiss", str(exc)) from exc
    return _out(db, action)
