"""Macro indicator series (FR-MD-08): what is stored, and a way to fetch now."""

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from folio.api.deps import DbDep, UserDep
from folio.db.models_analytics import MacroPoint, MacroSeries
from folio.jobs.macro import wanted_series
from folio.jobs.requests import enqueue_once

router = APIRouter(prefix="/macro", tags=["macro"])


class SeriesOut(BaseModel):
    code: str
    name: str
    source: str
    unit: str
    points: int
    last_date: dt.date | None
    last_value: Decimal | None
    configured: bool  # on the daily list (Settings, Macro) or named by a running strategy


@router.get("/series", response_model=list[SeriesOut])
def list_series(_user: UserDep, db: DbDep) -> list[SeriesOut]:
    """Every series on the list or already stored, with its latest value."""
    wanted = wanted_series(db)
    stored = {s.code: s for s in db.scalars(select(MacroSeries))}
    out = []
    for item in wanted:
        row = stored.pop(item.code, None)
        out.append(_out(db, row, item.code, item.name, item.source, item.unit, True))
    for row in stored.values():
        out.append(_out(db, row, row.code, row.name, row.source, row.unit, False))
    return out


def _out(
    db: DbDep,
    row: MacroSeries | None,
    code: str,
    name: str,
    source: str,
    unit: str,
    configured: bool,
) -> SeriesOut:
    count, last_date, last_value = 0, None, None
    if row is not None:
        count = db.scalar(select(func.count()).where(MacroPoint.series_id == row.id)) or 0
        last = db.scalars(
            select(MacroPoint)
            .where(MacroPoint.series_id == row.id)
            .order_by(MacroPoint.date.desc())
            .limit(1)
        ).first()
        if last is not None:
            last_date, last_value = last.date, last.value
    return SeriesOut(
        code=code,
        name=name,
        source=source,
        unit=unit,
        points=count,
        last_date=last_date,
        last_value=last_value,
        configured=configured,
    )


@router.post("/refresh", status_code=202)
def refresh(_user: UserDep, db: DbDep) -> dict[str, str]:
    """Fetch every series now; the worker picks the request up within seconds."""
    enqueue_once(db, "macro")
    return {"status": "queued"}
