"""When the background jobs run, and moving them (Settings, Schedules; FR-SY-09).

The jobs and their normal times are listed in `folio.jobs.cron`. A time the owner chooses is kept
under the `schedules` settings section and the worker is asked to apply it at once.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, ValidationError

from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.audit import write_audit
from folio.jobs.cron import JOBS, LOCAL_TZ, OVERRIDABLE, JobInfo, parse_cron
from folio.jobs.requests import enqueue
from folio.marketdata import exchanges
from folio.settings_schema import SchedulesSettings
from folio.settings_store import get_value, set_value

router = APIRouter(prefix="/schedules", tags=["schedules"])


class ScheduleOut(BaseModel):
    job_id: str
    title: str
    what: str
    normal: str  # when it normally runs, in words
    normal_cron: str
    cron: str  # what is in force: the owner's choice, or the normal one
    changed: bool
    timezone: str
    next_run: dt.datetime | None


class ExampleOut(BaseModel):
    cron: str
    words: str


class SchedulesOut(BaseModel):
    timezone: str
    items: list[ScheduleOut]
    fixed: list[str]  # what cannot be moved, in words
    examples: list[ExampleOut]


class ScheduleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cron: str | None  # null puts the job back to its normal time


EXAMPLES = [
    ("0 22 * * *", "every day at 22:00"),
    ("30 19 * * mon-fri", "weekdays at 19:30"),
    ("0 8 * * sun", "Sundays at 08:00"),
    ("*/30 * * * *", "every 30 minutes"),
    ("0 7,19 * * *", "every day at 07:00 and 19:00"),
    ("0 6 1 * *", "the first of every month at 06:00"),
]


def _overrides(db: DbDep) -> dict[str, str]:
    return dict(
        SchedulesSettings.model_validate(get_value(db, "section.schedules", {})).cron_overrides
    )


def _item(info: JobInfo, overrides: dict[str, str]) -> ScheduleOut:
    cron = overrides.get(info.job_id, info.cron)
    trigger = parse_cron(cron, info.tz)
    now = dt.datetime.now(dt.UTC)
    return ScheduleOut(
        job_id=info.job_id,
        title=info.title,
        what=info.what,
        normal=info.normal,
        normal_cron=info.cron,
        cron=cron,
        changed=info.job_id in overrides,
        timezone=info.tz,
        next_run=trigger.get_next_fire_time(None, now),
    )


@router.get("", response_model=SchedulesOut)
def list_schedules(_user: UserDep, db: DbDep) -> SchedulesOut:
    overrides = _overrides(db)
    return SchedulesOut(
        timezone=LOCAL_TZ,
        items=[_item(j, overrides) for j in JOBS],
        fixed=[
            f"Closing prices of {mic}: two hours after the exchange closes, on trading days"
            for mic in sorted(exchanges.EXCHANGES)
        ],
        examples=[ExampleOut(cron=c, words=w) for c, w in EXAMPLES],
    )


@router.put("/{job_id}", response_model=ScheduleOut)
def set_schedule(job_id: str, body: ScheduleIn, _user: UserDep, db: DbDep) -> ScheduleOut:
    info = OVERRIDABLE.get(job_id)
    if info is None:
        raise ApiError(404, "Unknown job", f"Jobs that can be moved: {', '.join(OVERRIDABLE)}.")
    overrides = _overrides(db)
    old = overrides.get(job_id)
    if body.cron is None or body.cron.strip() == info.cron:
        overrides.pop(job_id, None)
    else:
        overrides[job_id] = " ".join(body.cron.split())
    try:
        valid = SchedulesSettings.model_validate({"cron_overrides": overrides})
    except ValidationError as exc:
        first = exc.errors(include_url=False, include_context=False, include_input=False)[0]
        raise ApiError(
            422, "Invalid schedule", str(first["msg"]).removeprefix("Value error, ")
        ) from exc
    set_value(db, "section.schedules", valid.model_dump(mode="json"))
    write_audit(
        db,
        "user",
        "setting",
        "update",
        entity_id="schedules",
        diff={job_id: {"old": old, "new": overrides.get(job_id)}},
    )
    enqueue(db, "reschedule", {})  # the worker moves the running job now
    return _item(info, overrides)
