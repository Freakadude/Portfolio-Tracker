"""System page data: provider usage today, job runs and requests, the audit log."""

import datetime as dt
from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from folio.api.deps import DbDep, StoreDep, UserDep
from folio.api.errors import ApiError
from folio.db.models import AuditLog
from folio.db.models_ledger import JobRequest, JobRun, ProviderCall
from folio.jobs.requests import enqueue
from folio.jobs.scheduler import JOB_PARAMS
from folio.settings_store import load_section

router = APIRouter(tags=["system"])


class UsageOut(BaseModel):
    provider: str
    calls_today: int
    daily_budget: int | None  # null: no limit
    remaining: int | None
    enabled: bool
    has_key: bool | None  # null for providers that need no key


class RunOut(BaseModel):
    id: int
    job: str
    status: str
    params: dict[str, Any]
    started_at: dt.datetime
    finished_at: dt.datetime | None
    duration_seconds: float | None
    log: str | None


class RequestOut(BaseModel):
    id: int
    job: str
    params: dict[str, Any]
    status: str
    created_at: dt.datetime
    finished_at: dt.datetime | None
    error: str | None


class JobsOut(BaseModel):
    runs: list[RunOut]
    requests: list[RequestOut]
    available: dict[str, list[str]]  # job name -> the parameters it needs


class RunRequestIn(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)


class AuditOut(BaseModel):
    id: int
    ts: dt.datetime
    actor: str
    entity: str
    entity_id: str | None
    action: str
    diff: dict[str, Any] | None


class AuditPage(BaseModel):
    items: list[AuditOut]
    next_cursor: int | None


KEYED = {"eodhd", "twelvedata", "openfigi", "fred"}


@router.get("/system/usage", response_model=list[UsageOut])
def usage(_user: UserDep, db: DbDep, store: StoreDep) -> list[UsageOut]:
    """Calls made to each provider today (UTC) against its daily budget (FR-MD-10)."""
    config = load_section(db, "providers")
    today = datetime.now(UTC).date()
    counts = dict(
        db.execute(
            select(ProviderCall.provider, ProviderCall.count).where(ProviderCall.day == today)
        ).all()
    )
    out: list[UsageOut] = []
    for name, cfg in sorted(config.providers.items()):  # type: ignore[attr-defined]
        budget = cfg.daily_call_budget or None
        calls = int(counts.get(name, 0))
        out.append(
            UsageOut(
                provider=name,
                calls_today=calls,
                daily_budget=budget,
                remaining=None if budget is None else max(0, budget - calls),
                enabled=cfg.enabled,
                has_key=store.has(f"providers.{name}_api_key") if name in KEYED else None,
            )
        )
    return out


def _run_out(run: JobRun) -> RunOut:
    seconds = None
    if run.finished_at is not None:
        seconds = round((run.finished_at - run.started_at).total_seconds(), 3)
    return RunOut(
        id=run.id,
        job=run.job,
        status=run.status,
        params=dict(run.params or {}),
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_seconds=seconds,
        log=run.log,
    )


@router.get("/system/jobs", response_model=JobsOut)
def jobs(_user: UserDep, db: DbDep, limit: Annotated[int, Query(ge=1, le=200)] = 50) -> JobsOut:
    runs = db.scalars(select(JobRun).order_by(JobRun.id.desc()).limit(limit))
    requests = db.scalars(select(JobRequest).order_by(JobRequest.id.desc()).limit(20))
    return JobsOut(
        runs=[_run_out(r) for r in runs],
        requests=[
            RequestOut(
                id=r.id,
                job=r.job,
                params=dict(r.params or {}),
                status=r.status,
                created_at=r.created_at,
                finished_at=r.finished_at,
                error=r.error,
            )
            for r in requests
        ],
        available={name: list(needed) for name, needed in sorted(JOB_PARAMS.items())},
    )


@router.post("/system/jobs/{job}/run", response_model=RequestOut, status_code=202)
def run_job(job: str, body: RunRequestIn, _user: UserDep, db: DbDep) -> RequestOut:
    """Ask the worker to run a job now ("refresh prices now"). It is queued and picked up
    within a few seconds; the outcome appears in the job list."""
    needed = JOB_PARAMS.get(job)
    if needed is None:
        raise ApiError(404, "Unknown job", f"Jobs: {', '.join(sorted(JOB_PARAMS))}.")
    missing = [p for p in needed if p not in body.params]
    if missing:
        raise ApiError(422, "Missing parameter", f"The {job} job needs: {', '.join(missing)}.")
    request = enqueue(
        db, job, {k: v for k, v in body.params.items() if k in needed or k in ("day", "from")}
    )
    return RequestOut(
        id=request.id,
        job=request.job,
        params=dict(request.params or {}),
        status=request.status,
        created_at=request.created_at,
        finished_at=None,
        error=None,
    )


@router.get("/audit", response_model=AuditPage)
def audit(
    _user: UserDep,
    db: DbDep,
    entity: str | None = None,
    entity_id: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    cursor: int | None = None,
) -> AuditPage:
    """The append-only change log, newest first, with old and new values (FR-SY-08)."""
    query = select(AuditLog)
    if entity:
        query = query.where(AuditLog.entity == entity)
    if entity_id:
        query = query.where(AuditLog.entity_id == entity_id)
    if actor:
        query = query.where(AuditLog.actor == actor)
    if action:
        query = query.where(AuditLog.action == action)
    if from_ is not None:
        query = query.where(func.date(AuditLog.ts) >= from_.isoformat())
    if to is not None:
        query = query.where(func.date(AuditLog.ts) <= to.isoformat())
    if cursor is not None:
        query = query.where(AuditLog.id < cursor)
    rows = list(db.scalars(query.order_by(AuditLog.id.desc()).limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    return AuditPage(
        items=[
            AuditOut(
                id=r.id,
                ts=r.ts,
                actor=r.actor,
                entity=r.entity,
                entity_id=r.entity_id,
                action=r.action,
                diff=r.diff,
            )
            for r in rows
        ],
        next_cursor=rows[-1].id if more and rows else None,
    )
