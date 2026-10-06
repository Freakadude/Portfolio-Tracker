"""Export the ledger and the positions (FR-TX-13), as CSV or JSON."""

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Response

from folio import exports
from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.db.models import Account

router = APIRouter(prefix="/export", tags=["export"])

Format = Literal["csv", "json"]


def _check_account(db: DbDep, account: int | None) -> None:
    if account is None:
        return
    found = db.get(Account, account)
    if found is None or found.deleted_at is not None:
        raise ApiError(404, "Not found", "That account does not exist.")


def _file(body: str, kind: str, form: Format, today: dt.date) -> Response:
    media = "text/csv; charset=utf-8" if form == "csv" else "application/json"
    name = f"folio-{kind}-{today.isoformat()}.{form}"
    return Response(
        body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'}
    )


@router.get("/transactions")
def export_transactions(
    _user: UserDep,
    db: DbDep,
    format: Format = "csv",  # noqa: A002 - the query parameter is part of the API
    account: int | None = None,
) -> Response:
    """Every posted transaction, in the columns the CSV import wizard recognises, so the file
    reads back into Folio without any choices to make."""
    _check_account(db, account)
    today = dt.date.today()
    rows = exports.transaction_rows(db, account)
    body = (
        exports.transactions_csv(rows)
        if format == "csv"
        else exports.as_json("transactions", rows, today)
    )
    return _file(body, "transactions", format, today)


@router.get("/positions")
def export_positions(
    _user: UserDep,
    db: DbDep,
    format: Format = "csv",  # noqa: A002 - the query parameter is part of the API
    account: int | None = None,
) -> Response:
    """The open positions with their cost basis and value on the last prices."""
    _check_account(db, account)
    today = dt.date.today()
    rows = exports.position_rows(db, today, account)
    body = (
        exports.positions_csv(rows)
        if format == "csv"
        else exports.as_json("positions", rows, today)
    )
    return _file(body, "positions", format, today)
