"""Portfolio overview. Ratio fields are fractions (0.05 means 5 percent)."""

import datetime as dt
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from folio import analytics_service as svc
from folio.analytics.valuation import (
    PeriodFigures,
    period_figures,
    pnl_ratio_since_start,
    resolve_period,
)
from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.db.models import Account
from folio.portfolio import Valuation

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


class PeriodOut(BaseModel):
    key: str
    start: dt.date
    end: dt.date
    value_start_eur: Decimal
    value_end_eur: Decimal
    net_flows_eur: Decimal
    income_eur: Decimal
    costs_eur: Decimal
    pnl_eur: Decimal
    pnl_ratio: Decimal | None


class ChangeOut(BaseModel):
    pnl_eur: Decimal
    pnl_ratio: Decimal | None


class SummaryOut(BaseModel):
    as_of: dt.date
    price_date: dt.date | None  # the newest close behind the value
    account_id: int | None
    value_eur: Decimal
    net_contributions_eur: Decimal
    income_eur: Decimal
    costs_eur: Decimal
    total_pnl_eur: Decimal
    total_pnl_ratio: Decimal | None
    unvalued_positions: int
    cash_eur: Decimal | None  # null while no account tracks cash
    day_change: ChangeOut
    period: PeriodOut


class HistoryPoint(BaseModel):
    date: dt.date
    value_eur: Decimal
    net_contributions_eur: Decimal
    twr_index: Decimal  # time-weighted growth, 1 on the first day shown
    drawdown: Decimal  # distance below the running peak of that index (0 or negative)
    unvalued_positions: int
    is_peildatum: bool


def _period_out(key: str, figures: PeriodFigures) -> PeriodOut:
    return PeriodOut(
        key=key,
        start=figures.start,
        end=figures.end,
        value_start_eur=figures.value_start_eur,
        value_end_eur=figures.value_end_eur,
        net_flows_eur=figures.net_flows_eur,
        income_eur=figures.income_eur,
        costs_eur=figures.costs_eur,
        pnl_eur=figures.pnl_eur,
        pnl_ratio=figures.pnl_ratio,
    )


@router.get("/summary", response_model=SummaryOut)
def summary(
    _user: UserDep,
    db: DbDep,
    period: str = "1M",
    as_of: date | None = None,
    account: int | None = None,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
) -> SummaryOut:
    """Value, net contributions, total P&L and the change over a period (FR-PF-01)."""
    if account is not None:
        found = db.get(Account, account)
        if found is None or found.deleted_at is not None:
            raise ApiError(404, "Not found", "That account does not exist.")
    today = as_of or date.today()
    valuation = Valuation.load(db, account_id=account)
    try:
        start, end = resolve_period(period, today, valuation.first_date(), from_, to)
    except ValueError as exc:
        raise ApiError(422, "Invalid period", str(exc)) from exc
    now = valuation.point(end if period.upper() == "CUSTOM" else today)
    over_period = period_figures(valuation.point(start), now)
    price_dates = [h.price.date for h in now.holdings if h.price is not None]
    # the last price day against the one before it, not the calendar yesterday: on a weekend or
    # before the close that day has the same price as today and the change showed 0
    latest = min(now.day, max(price_dates)) if price_dates else now.day
    day = period_figures(valuation.point(latest - dt.timedelta(days=1)), now)
    return SummaryOut(
        as_of=now.day,
        price_date=max(price_dates) if price_dates else None,
        account_id=account,
        value_eur=now.value_eur,
        net_contributions_eur=now.net_contributions_eur,
        income_eur=now.income_eur,
        costs_eur=now.costs_eur,
        total_pnl_eur=now.total_pnl_eur,
        total_pnl_ratio=pnl_ratio_since_start(now),
        unvalued_positions=now.unvalued,
        cash_eur=now.cash_eur if valuation.tracks_cash else None,
        day_change=ChangeOut(pnl_eur=day.pnl_eur, pnl_ratio=day.pnl_ratio),
        period=_period_out(period.upper(), over_period),
    )


@router.get("/history", response_model=list[HistoryPoint])
def history(
    _user: UserDep,
    db: DbDep,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    account: int | None = None,
    as_of: date | None = None,
) -> list[HistoryPoint]:
    """Daily value against net contributions from the first transaction (FR-PF-02), with the
    time-weighted index and the drawdown from the running peak. Days are those on which
    something happened or a close was stored; between them the value is unchanged."""
    if account is not None:
        found = db.get(Account, account)
        if found is None or found.deleted_at is not None:
            raise ApiError(404, "Not found", "That account does not exist.")
    ctx = svc.get_context(db, as_of or date.today(), account)
    return [
        HistoryPoint(
            date=r.day,
            value_eur=r.value,
            net_contributions_eur=r.net_contributions,
            twr_index=r.twr_index,
            drawdown=r.drawdown,
            unvalued_positions=r.unvalued,
            is_peildatum=r.is_peildatum,
        )
        for r in svc.history(ctx, from_, to)
    ]
