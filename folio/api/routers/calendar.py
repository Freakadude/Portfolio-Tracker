"""The event calendar (FR-NW-09): upcoming events, and events the owner adds, changes or removes."""

import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.audit import write_audit
from folio.db.base import utcnow
from folio.db.models_insight import CalendarEvent
from folio.db.models_ledger import Instrument
from folio.jobs.requests import enqueue
from folio.news.calendar import MAX_DAYS, CalendarError, add_event, live, upcoming

router = APIRouter(prefix="/calendar", tags=["news"])


class CalendarEventOut(BaseModel):
    id: int
    kind: Literal["earnings", "central_bank", "custom"]
    date: dt.date
    in_days: int
    title: str
    instrument_id: int | None
    instrument_name: str | None
    source: Literal["shipped", "eodhd", "owner"]
    detail: str
    brief_done: bool  # the evening-before brief or reminder has been sent


class CalendarEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    date: dt.date
    kind: Literal["earnings", "central_bank", "custom"] = "custom"
    instrument_id: int | None = None
    detail: str = Field(default="", max_length=2000)


class CalendarEventChanges(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    date: dt.date | None = None
    detail: str | None = Field(default=None, max_length=2000)
    instrument_id: int | None = None


def _out(db: DbDep, event: CalendarEvent, today: dt.date) -> CalendarEventOut:
    instrument = db.get(Instrument, event.instrument_id) if event.instrument_id else None
    return CalendarEventOut(
        id=event.id,
        kind=event.kind,
        date=event.event_date,
        in_days=(event.event_date - today).days,
        title=event.title,
        instrument_id=event.instrument_id,
        instrument_name=None if instrument is None else instrument.name,
        source=event.source,
        detail=event.detail,
        brief_done=event.brief_sent_at is not None,
    )


def _fail(exc: CalendarError) -> ApiError:
    status = 404 if "does not exist" in str(exc) and "instrument" not in str(exc) else 422
    return ApiError(status, "Not found" if status == 404 else "Cannot save event", str(exc))


@router.get("/events", response_model=list[CalendarEventOut])
def list_events(
    _user: UserDep,
    db: DbDep,
    days: Annotated[int, Query(ge=1, le=MAX_DAYS)] = 60,
    past_days: Annotated[int, Query(ge=0, le=30)] = 0,
) -> list[CalendarEventOut]:
    """Events from `past_days` ago to `days` ahead, soonest first."""
    today = utcnow().date()
    return [_out(db, e, today) for e in upcoming(db, today, days, past_days)]


@router.post("/events", response_model=CalendarEventOut, status_code=201)
def create_event(body: CalendarEventIn, _user: UserDep, db: DbDep) -> CalendarEventOut:
    try:
        event = add_event(
            db,
            title=body.title,
            day=body.date,
            kind=body.kind,
            instrument_id=body.instrument_id,
            detail=body.detail,
        )
    except CalendarError as exc:
        raise _fail(exc) from exc
    write_audit(
        db,
        "user",
        "calendar_event",
        "create",
        entity_id=event.id,
        diff={"title": body.title, "date": body.date.isoformat()},
    )
    return _out(db, event, utcnow().date())


@router.patch("/events/{event_id}", response_model=CalendarEventOut)
def change_event(
    event_id: int, body: CalendarEventChanges, _user: UserDep, db: DbDep
) -> CalendarEventOut:
    try:
        event = live(db, event_id)
    except CalendarError as exc:
        raise _fail(exc) from exc
    given = body.model_dump(exclude_unset=True)
    diff: dict[str, dict[str, str | None]] = {}
    if "title" in given and given["title"] is not None:
        diff["title"] = {"old": event.title, "new": " ".join(given["title"].split())}
        event.title = diff["title"]["new"] or event.title
    if "date" in given and given["date"] is not None and given["date"] != event.event_date:
        diff["date"] = {"old": event.event_date.isoformat(), "new": given["date"].isoformat()}
        event.event_date = given["date"]
        event.brief_sent_at = None  # the brief belongs to the new day
    if "detail" in given and given["detail"] is not None:
        event.detail = given["detail"].strip()
    if "instrument_id" in given:
        if (
            given["instrument_id"] is not None
            and db.get(Instrument, given["instrument_id"]) is None
        ):
            raise ApiError(422, "Cannot save event", "That instrument does not exist.")
        event.instrument_id = given["instrument_id"]
    if diff:
        write_audit(db, "user", "calendar_event", "update", entity_id=event.id, diff=diff)
    db.flush()
    return _out(db, event, utcnow().date())


@router.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: int, _user: UserDep, db: DbDep) -> None:
    try:
        event = live(db, event_id)
    except CalendarError as exc:
        raise _fail(exc) from exc
    event.deleted_at = utcnow()  # it stays, so a ready-made date is not brought back
    write_audit(
        db,
        "user",
        "calendar_event",
        "delete",
        entity_id=event.id,
        diff={"title": event.title, "date": event.event_date.isoformat()},
    )


@router.post("/refresh", status_code=202)
def refresh(_user: UserDep, db: DbDep) -> dict[str, bool]:
    """Ask the worker to write the ready-made dates and, if switched on, fetch earnings dates."""
    enqueue(db, "calendar", {})
    return {"queued": True}
