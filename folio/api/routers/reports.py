"""Reports (FR-TX-12): realized result and income per calendar year, with CSV export."""

import datetime as dt
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from folio import reports
from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.db.models import Account

router = APIRouter(prefix="/reports", tags=["reports"])


class RealizedOut(BaseModel):
    account: str
    instrument: str
    isin: str | None
    quantity: Decimal
    proceeds_eur: Decimal
    cost_eur: Decimal
    result_eur: Decimal


class IncomeOut(BaseModel):
    account: str
    instrument: str
    isin: str | None
    gross_eur: Decimal
    withholding_eur: Decimal
    net_eur: Decimal


class YearReportOut(BaseModel):
    year: int
    realized: list[RealizedOut]
    income: list[IncomeOut]
    realized_total_eur: Decimal
    income_gross_eur: Decimal
    withholding_eur: Decimal
    costs_eur: Decimal


def _check_account(db: Session, account: int | None) -> None:
    if account is None:
        return
    found = db.get(Account, account)
    if found is None or found.deleted_at is not None:
        raise ApiError(404, "Not found", "That account does not exist.")


@router.get("/years", response_model=list[int])
def years(_user: UserDep, db: DbDep) -> list[int]:
    """The calendar years that have a sale or income to report, newest first."""
    return reports.report_years(db)


@router.get("/realized", response_model=YearReportOut)
def realized(
    _user: UserDep,
    db: DbDep,
    year: int | None = None,
    account: int | None = None,
    format: Literal["json", "csv"] = "json",  # noqa: A002 - the query parameter is part of the API
) -> YearReportOut | Response:
    """Realized result (from the lot matches) and income for one calendar year, per account
    and instrument. `format=csv` downloads the same figures as a spreadsheet file."""
    _check_account(db, account)
    chosen = year or date.today().year
    if not 1990 <= chosen <= dt.date.today().year + 1:
        raise ApiError(422, "Invalid year", "Choose a calendar year such as 2025.")
    report = reports.year_report(db, chosen, account)
    if format == "csv":
        return Response(
            reports.to_csv(report),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="folio-realized-{chosen}.csv"'},
        )
    return YearReportOut(
        year=report.year,
        realized=[
            RealizedOut(
                account=r.account,
                instrument=r.instrument,
                isin=r.isin,
                quantity=r.quantity,
                proceeds_eur=r.proceeds_eur,
                cost_eur=r.cost_eur,
                result_eur=r.result_eur,
            )
            for r in report.realized
        ],
        income=[
            IncomeOut(
                account=i.account,
                instrument=i.instrument,
                isin=i.isin,
                gross_eur=i.gross_eur,
                withholding_eur=i.withholding_eur,
                net_eur=i.net_eur,
            )
            for i in report.income
        ],
        realized_total_eur=report.realized_total_eur,
        income_gross_eur=report.income_gross_eur,
        withholding_eur=report.withholding_eur,
        costs_eur=report.costs_eur,
    )
