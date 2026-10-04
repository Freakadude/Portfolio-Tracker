from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.audit import write_audit
from folio.db.base import utcnow
from folio.db.models import Account
from folio.db.models_ledger import LedgerTransaction
from folio.domain import CostBasisMethod
from folio.ledger_service import TransactionError, change_cost_basis_method

router = APIRouter(prefix="/accounts", tags=["accounts"])


class AccountOut(BaseModel):
    id: int
    name: str
    broker: str | None
    cost_basis_method: str
    base_currency: str
    active: bool
    transaction_count: int


class AccountIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    broker: str | None = Field(default=None, max_length=100)
    cost_basis_method: Literal["FIFO", "AVG"] = "FIFO"


class AccountChanges(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    broker: str | None = Field(default=None, max_length=100)
    cost_basis_method: Literal["FIFO", "AVG"] | None = None
    active: bool | None = None


def _count(db: Session, account_id: int) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(LedgerTransaction)
            .where(
                LedgerTransaction.account_id == account_id, LedgerTransaction.deleted_at.is_(None)
            )
        )
        or 0
    )


def _out(db: Session, account: Account) -> AccountOut:
    return AccountOut(
        id=account.id,
        name=account.name,
        broker=account.broker,
        cost_basis_method=account.cost_basis_method,
        base_currency=account.base_currency,
        active=account.active,
        transaction_count=_count(db, account.id),
    )


def _load(db: Session, account_id: int) -> Account:
    account = db.get(Account, account_id)
    if account is None or account.deleted_at is not None:
        raise ApiError(404, "Not found", "That account does not exist.")
    return account


@router.get("", response_model=list[AccountOut])
def list_accounts(_user: UserDep, db: DbDep) -> list[AccountOut]:
    accounts = db.scalars(
        select(Account).where(Account.deleted_at.is_(None)).order_by(Account.name)
    )
    return [_out(db, a) for a in accounts]


@router.post("", response_model=AccountOut, status_code=201)
def create_account(body: AccountIn, _user: UserDep, db: DbDep) -> AccountOut:
    account = Account(
        name=body.name.strip(), broker=body.broker, cost_basis_method=body.cost_basis_method
    )
    db.add(account)
    db.flush()
    write_audit(
        db, "user", "account", "create", entity_id=account.id,
        diff={"name": account.name, "cost_basis_method": account.cost_basis_method},
    )  # fmt: skip
    return _out(db, account)


@router.patch("/{account_id}", response_model=AccountOut)
def update_account(account_id: int, body: AccountChanges, _user: UserDep, db: DbDep) -> AccountOut:
    account = _load(db, account_id)
    given = body.model_dump(exclude_unset=True)
    method = given.pop("cost_basis_method", None)
    diff = {}
    for key, value in given.items():
        old = getattr(account, key)
        if old != value:
            diff[key] = {"old": old, "new": value}
            setattr(account, key, value)
    if diff:
        write_audit(db, "user", "account", "update", entity_id=account.id, diff=diff)
    if method is not None:
        try:  # recomputes every derived number, so it can be refused (an oversell cannot occur
            change_cost_basis_method(db, account, CostBasisMethod(method))  # under either method)
        except TransactionError as exc:
            raise ApiError(422, "Cannot switch method", str(exc)) from exc
    return _out(db, account)


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: int, _user: UserDep, db: DbDep) -> None:
    account = _load(db, account_id)
    count = _count(db, account.id)
    if count:
        raise ApiError(
            409,
            "Account in use",
            f"{account.name} has {count} transaction{'s' if count != 1 else ''}. Delete or move "
            "them first, or mark the account inactive instead.",
        )
    account.deleted_at = utcnow()
    write_audit(db, "user", "account", "delete", entity_id=account.id, diff={"name": account.name})
