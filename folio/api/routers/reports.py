"""Reports (FR-TX-12): realized result and income per calendar year, with CSV export."""

import datetime as dt
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from folio import reports, tax_report
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


class TaxHoldingOut(BaseModel):
    account: str
    instrument: str
    isin: str | None
    quantity: Decimal
    value_eur: Decimal | None
    cost_basis_eur: Decimal


class TaxSupportOut(BaseModel):
    year: int
    start: date
    end: date
    partial: bool  # the year is not over: the figures run to `end`
    value_start_eur: Decimal
    value_end_eur: Decimal
    unvalued_start: int
    unvalued_end: int
    money_in_eur: Decimal
    money_out_eur: Decimal
    net_contributions_eur: Decimal
    income_gross_eur: Decimal
    withholding_eur: Decimal
    income_net_eur: Decimal
    trade_costs_eur: Decimal
    other_costs_eur: Decimal
    realized_proceeds_eur: Decimal
    realized_cost_eur: Decimal
    realized_result_eur: Decimal
    unrealized_start_eur: Decimal
    unrealized_end_eur: Decimal
    unrealized_change_eur: Decimal
    holdings_start: list[TaxHoldingOut]
    holdings_end: list[TaxHoldingOut]
    note: str


TAX_NOTE = (
    "Support for filling in a tax return, not tax advice. Values are the closing values of the "
    "last day with a price on or before the date, in euro at the rates stored on each "
    "transaction. Money put in and taken out follow the returns' definition of external flows: "
    "purchases and deposits in, sales and withdrawals out."
)


@router.get("/tax-years", response_model=list[int])
def tax_years(_user: UserDep, db: DbDep) -> list[int]:
    """The calendar years the tax-support report can be made for, newest first."""
    return reports.history_years(db, dt.date.today())


def _holding(h: tax_report.HoldingOn) -> TaxHoldingOut:
    return TaxHoldingOut(
        account=h.account,
        instrument=h.instrument,
        isin=h.isin,
        quantity=h.quantity,
        value_eur=h.value_eur,
        cost_basis_eur=h.cost_basis_eur,
    )


@router.get("/tax-support", response_model=TaxSupportOut)
def tax_support(
    _user: UserDep,
    db: DbDep,
    year: int | None = None,
    account: int | None = None,
    format: Literal["json", "csv"] = "json",  # noqa: A002 - the query parameter is part of the API
) -> TaxSupportOut | Response:
    """The annual tax-support report (FR-PF-11): value on 1 January and 31 December, money in and
    out, income, costs, realized gains and the change in unrealized result. `format=csv`
    downloads it as a spreadsheet; the web page prints to PDF."""
    _check_account(db, account)
    today = dt.date.today()
    chosen = year or today.year
    if not 1990 <= chosen <= today.year:
        raise ApiError(422, "Invalid year", "Choose a calendar year such as 2025.")
    r = tax_report.tax_support(db, chosen, today, account)
    if format == "csv":
        return Response(
            tax_report.to_csv(r),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="folio-tax-support-{chosen}.csv"'
            },
        )
    return TaxSupportOut(
        year=r.year,
        start=r.start,
        end=r.end,
        partial=r.partial,
        value_start_eur=r.value_start_eur,
        value_end_eur=r.value_end_eur,
        unvalued_start=r.unvalued_start,
        unvalued_end=r.unvalued_end,
        money_in_eur=r.money_in_eur,
        money_out_eur=r.money_out_eur,
        net_contributions_eur=r.net_contributions_eur,
        income_gross_eur=r.income_gross_eur,
        withholding_eur=r.withholding_eur,
        income_net_eur=r.income_net_eur,
        trade_costs_eur=r.trade_costs_eur,
        other_costs_eur=r.other_costs_eur,
        realized_proceeds_eur=r.realized_proceeds_eur,
        realized_cost_eur=r.realized_cost_eur,
        realized_result_eur=r.realized_result_eur,
        unrealized_start_eur=r.unrealized_start_eur,
        unrealized_end_eur=r.unrealized_end_eur,
        unrealized_change_eur=r.unrealized_change_eur,
        holdings_start=[_holding(h) for h in r.holdings_start],
        holdings_end=[_holding(h) for h in r.holdings_end],
        note=TAX_NOTE,
    )
