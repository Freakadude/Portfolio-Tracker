from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from folio.api.deps import SESSION_COOKIE, DbDep, UserDep
from folio.api.errors import ApiError
from folio.api.routers.auth import MeOut, issue_session
from folio.audit import write_audit
from folio.db.models import Account, User
from folio.security.sessions import resolve_session
from folio.security.users import create_user
from folio.settings_store import get_value, set_value

router = APIRouter(prefix="/setup", tags=["setup"])

COMPLETE_KEY = "setup.complete"


class SetupStatus(BaseModel):
    needs_owner: bool
    authenticated: bool
    has_account: bool
    setup_complete: bool


class OwnerIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024)


class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    broker: str | None = Field(default=None, max_length=100)
    cost_basis_method: Literal["FIFO", "AVG"] = "FIFO"


class AccountOut(BaseModel):
    id: int
    name: str
    broker: str | None
    cost_basis_method: str


@router.get("/status", response_model=SetupStatus)
def status(request: Request, db: DbDep) -> SetupStatus:
    users = db.scalar(select(func.count()).select_from(User)) or 0
    accounts = db.scalar(select(func.count()).select_from(Account)) or 0
    signed_in = resolve_session(db, request.cookies.get(SESSION_COOKIE)) is not None
    return SetupStatus(
        needs_owner=users == 0,
        authenticated=signed_in,
        has_account=accounts > 0,
        setup_complete=bool(get_value(db, COMPLETE_KEY, False)),
    )


@router.post("/owner", response_model=MeOut, status_code=201)
def create_owner(body: OwnerIn, request: Request, response: Response, db: DbDep) -> MeOut:
    """First-run only: there is exactly one owner and no other way to create accounts."""
    if (db.scalar(select(func.count()).select_from(User)) or 0) > 0:
        raise ApiError(409, "Setup already done", "An owner account already exists.")
    try:
        user = create_user(db, body.username, body.password)
    except ValueError as exc:
        raise ApiError(422, "Cannot create owner", str(exc)) from exc
    write_audit(db, "user", "user", "create", entity_id=user.id, diff={"username": user.username})
    issue_session(request, response, db, user, remember=False)
    return MeOut(username=user.username)


@router.post("/account", response_model=AccountOut, status_code=201)
def create_first_account(body: AccountIn, _user: UserDep, db: DbDep) -> AccountOut:
    account = Account(
        name=body.name.strip(), broker=body.broker, cost_basis_method=body.cost_basis_method
    )
    db.add(account)
    db.flush()
    write_audit(
        db,
        "user",
        "account",
        "create",
        entity_id=account.id,
        diff={"name": account.name, "cost_basis_method": account.cost_basis_method},
    )
    return AccountOut(
        id=account.id,
        name=account.name,
        broker=account.broker,
        cost_basis_method=account.cost_basis_method,
    )


@router.post("/complete", status_code=204)
def complete(_user: UserDep, db: DbDep) -> None:
    if (db.scalar(select(func.count()).select_from(Account)) or 0) == 0:
        raise ApiError(409, "Add an account first", "Create at least one account to finish setup.")
    set_value(db, COMPLETE_KEY, True)
    write_audit(db, "user", "setup", "complete")
