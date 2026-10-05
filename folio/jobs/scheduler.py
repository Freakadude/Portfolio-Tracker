"""The worker's schedule (APScheduler 3) and the job-request queue.

Scheduled: closes two hours after each exchange closes (skipped on holidays), ECB rates, gap
repair, splits and dividends, nightly snapshots, nightly backup. A persistent job store means a
run missed while the worker was down happens once after it restarts (coalesced, NFR-05).
User actions that need the worker ("refresh prices now", a backfill after adding an instrument)
arrive as `job_request` rows, which are polled every five seconds.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.base import BaseJobStore
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from folio.backup import BackupError, create_backup
from folio.config import Settings
from folio.db.base import utcnow
from folio.db.models_ledger import JobRequest
from folio.jobs.agent import agent_run_job, agent_tick, outcomes_job
from folio.jobs.context import JobContext
from folio.jobs.lookthrough import lookthrough_job
from folio.jobs.macro import macro_job
from folio.jobs.market import (
    actions_job,
    backfill_job,
    eod_job,
    fx_job,
    gap_job,
    quotes_job,
    refresh_job,
    retention_job,
)
from folio.jobs.news import news_job
from folio.jobs.notify import notify_job
from folio.jobs.portfolio import snapshots_job
from folio.jobs.runner import JobLog, JobResult, run_job
from folio.jobs.strategies import rules_job
from folio.logging import get_logger
from folio.marketdata import exchanges

log = get_logger("folio.scheduler")

LOCAL_TZ = "Europe/Amsterdam"
MISFIRE_GRACE_SECONDS = 6 * 3600
POLL_SECONDS = 5
AGENT_SECONDS = 300  # what is due for the AI agent (FR-AG-01)
NOTIFY_SECONDS = 60  # pushes, digests and new signals (FR-NT-04 to FR-NT-06)


# --- job requests -------------------------------------------------------------------------------


def _date(value: object) -> date | None:
    return None if value in (None, "") else date.fromisoformat(str(value))


def backup_job(ctx: JobContext, settings: Settings, *, include_secrets: bool = True) -> JobResult:
    def body(db, job_log: JobLog) -> None:  # type: ignore[no-untyped-def]
        try:
            result = create_backup(
                settings.db_url,
                settings.backup_dir,
                extra_dir=settings.extra_backup_dir,
                include_secrets=include_secrets,
                now=ctx.now(),
            )
        except BackupError as exc:
            job_log.error(str(exc))
            return
        job_log.info(
            f"Backup {result.path.name} ({result.size} bytes), {len(result.pruned)} old removed"
        )
        if result.copied_to:
            job_log.info(f"Copied to {result.copied_to}")

    return run_job(ctx, "backup", body)


# What each job needs in its parameters (used by the API and the command line).
JOB_PARAMS: dict[str, tuple[str, ...]] = {
    "backfill": ("listing_id",),
    "eod": ("mic",),
    "fx": (),
    "gaps": (),
    "snapshots": (),
    "actions": (),
    "backup": (),
    "refresh": (),
    "quotes": (),
    "retention": (),
    "rules": (),
    "macro": (),
    "lookthrough": ("instrument_id",),
    "news": ("source_id",),
    "agent_run": ("run_type",),
    "outcomes": (),
}


def _refresh(ctx: JobContext) -> JobResult:
    result = refresh_job(ctx)
    snapshots_job(ctx)  # new closes change the recent values
    rules_job(ctx)  # and may move a sleeve out of its band
    return result


def handlers(
    ctx: JobContext, settings: Settings
) -> dict[str, Callable[[dict[str, object]], JobResult]]:
    """What a job request may ask for, by name."""
    return {
        "backfill": lambda p: backfill_job(ctx, int(str(p["listing_id"]))),
        "snapshots": lambda p: snapshots_job(ctx, _date(p.get("from"))),
        "eod": lambda p: eod_job(ctx, str(p["mic"]), _date(p.get("day"))),
        "fx": lambda p: fx_job(ctx),
        "gaps": lambda p: gap_job(ctx),
        "actions": lambda p: actions_job(ctx),
        "backup": lambda p: backup_job(ctx, settings),
        "refresh": lambda p: _refresh(ctx),
        "quotes": lambda p: quotes_job(ctx),
        "retention": lambda p: retention_job(ctx),
        "rules": lambda p: rules_job(ctx),
        "macro": lambda p: macro_job(ctx),
        "outcomes": lambda p: outcomes_job(ctx),
        "agent_run": lambda p: agent_run_job(
            ctx,
            "daily_review" if p.get("run_type") == "daily_review" else "on_demand",
            "on_demand",
            None if not p.get("question") else str(p["question"])[:500],
        ),
        "news": lambda p: news_job(
            ctx, None if p.get("source_id") is None else int(str(p["source_id"]))
        ),
        "lookthrough": lambda p: lookthrough_job(
            ctx, None if p.get("instrument_id") is None else int(str(p["instrument_id"]))
        ),
    }


def process_job_requests(ctx: JobContext, settings: Settings) -> int:
    """Run every pending request, oldest first. A failing request is marked failed with the
    reason and never stops the others. Returns how many were handled."""
    table = handlers(ctx, settings)
    handled = 0
    while True:
        with ctx.session_factory() as db:
            request = db.scalars(
                select(JobRequest)
                .where(JobRequest.status == "pending")
                .order_by(JobRequest.id)
                .limit(1)
            ).first()
            if request is None:
                return handled
            request.status, request.picked_up_at = "running", utcnow()
            request_id, job, params = request.id, request.job, dict(request.params or {})
            db.commit()
        status, error = "done", None
        handler = table.get(job)
        if handler is None:
            status, error = "failed", f"Unknown job {job!r}."
        else:
            try:
                result = handler(params)
                if result.status != "ok":
                    status, error = "failed", result.log
            except Exception as exc:  # noqa: BLE001 - one bad request must not stop the queue
                status, error = "failed", f"{type(exc).__name__}: {exc}"
                log.exception("job request failed", job=job)
        with ctx.session_factory() as db:
            done = db.get(JobRequest, request_id)
            if done is not None:
                done.status, done.finished_at, done.error = status, utcnow(), error
                db.commit()
        handled += 1


# --- schedule -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Schedule:
    job_id: str
    trigger: BaseTrigger


def eod_trigger(mic: str) -> CronTrigger:
    """Two hours after the usual close, in the exchange's own timezone, on weekdays. Holidays
    are handled by the job itself, which does nothing on a closed day."""
    calendar = exchanges.calendar(mic)
    close = calendar.close_times[0][1]
    minutes = (
        close.hour * 60 + close.minute + int(exchanges.EOD_DELAY.total_seconds() // 60)
    ) % 1440
    return CronTrigger(
        day_of_week="mon-fri", hour=minutes // 60, minute=minutes % 60, timezone=str(calendar.tz)
    )


def build_schedules() -> list[Schedule]:
    schedules = [Schedule(f"eod-{mic}", eod_trigger(mic)) for mic in exchanges.EXCHANGES]
    local = {"timezone": LOCAL_TZ}
    schedules += [
        Schedule("fx", CronTrigger(hour=16, minute=30, **local)),  # the ECB publishes about 16:00
        Schedule("gaps", CronTrigger(hour=22, minute=0, **local)),
        Schedule("snapshots", CronTrigger(hour=23, minute=0, **local)),
        Schedule("backup", CronTrigger(hour=3, minute=0, **local)),
        Schedule("retention", CronTrigger(hour=3, minute=30, **local)),
        Schedule("rules", CronTrigger(hour=23, minute=15, **local)),  # after the snapshots
        # FRED publishes the US daily series overnight, the ECB in the afternoon
        Schedule("macro", CronTrigger(hour=7, minute=0, **local)),
        # after the closes, so a horizon that just passed finds its price (FR-AG-06)
        Schedule("outcomes", CronTrigger(hour=23, minute=30, **local)),
        # issuers publish holdings daily; a monthly refresh is what FR-MD-09 asks for
        Schedule("lookthrough", CronTrigger(day=1, hour=6, minute=0, **local)),
        # every 15 minutes from 07:00 to 23:00 local time and hourly overnight (FR-NW-02);
        # each source also keeps to its own interval
        Schedule(
            "news",
            OrTrigger(
                [
                    CronTrigger(minute="*/15", hour="7-22", **local),
                    CronTrigger(minute=0, hour="23,0-6", **local),
                ]
            ),
        ),
        Schedule("quotes", CronTrigger(minute="*/15", timezone="UTC")),  # FR-MD-05
        Schedule("actions", CronTrigger(day_of_week="sun", hour=9, minute=0, **local)),
    ]
    return schedules


# A persistent job store pickles each job's callable, so jobs are registered by importable name
# and read what they need from this module-level runtime, set once when the worker starts.
_runtime: tuple[JobContext, Settings] | None = None


def set_runtime(ctx: JobContext, settings: Settings) -> None:
    global _runtime  # noqa: PLW0603 - the one place the worker's wiring lives
    _runtime = (ctx, settings)


def _rt() -> tuple[JobContext, Settings]:
    if _runtime is None:
        raise RuntimeError("The scheduler runtime is not set; call set_runtime first.")
    return _runtime


def run_eod(mic: str) -> None:
    ctx = _rt()[0]
    result = eod_job(ctx, mic, only_if_tracked=True)
    if result.status == "ok":
        rules_job(ctx)  # new closes can breach a band or a level (FR-ST-03)


def run_fx() -> None:
    fx_job(_rt()[0])


def run_gaps() -> None:
    gap_job(_rt()[0])


def run_snapshots() -> None:
    snapshots_job(_rt()[0])


def run_backup() -> None:
    ctx, settings = _rt()
    backup_job(ctx, settings)


def run_actions() -> None:
    actions_job(_rt()[0])


def run_quotes() -> None:
    quotes_job(_rt()[0], only_if_open=True)


def run_retention() -> None:
    retention_job(_rt()[0])


def run_rules() -> None:
    rules_job(_rt()[0])


def run_macro() -> None:
    macro_job(_rt()[0])


def run_outcomes() -> None:
    outcomes_job(_rt()[0])


def run_lookthrough() -> None:
    lookthrough_job(_rt()[0])


def run_news() -> None:
    news_job(_rt()[0])


def run_agent_tick() -> None:
    agent_tick(_rt()[0])


def run_requests() -> None:
    ctx, settings = _rt()
    process_job_requests(ctx, settings)


def run_notify() -> None:
    notify_job(_rt()[0])


_MODULE = "folio.jobs.scheduler"


def make_scheduler(
    settings: Settings, ctx: JobContext, *, persistent: bool = True
) -> BackgroundScheduler:
    """Scheduler with every job registered. One scheduled job runs at a time: SQLite has a
    single writer, and the nightly jobs are short."""
    set_runtime(ctx, settings)
    store: BaseJobStore = (
        SQLAlchemyJobStore(url=settings.db_url, tablename="apscheduler_jobs")
        if persistent
        else MemoryJobStore()
    )
    scheduler = BackgroundScheduler(
        jobstores={"default": store},
        executors={"default": ThreadPoolExecutor(1)},
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": MISFIRE_GRACE_SECONDS,
        },
    )
    for schedule in build_schedules():
        if schedule.job_id.startswith("eod-"):
            scheduler.add_job(
                f"{_MODULE}:run_eod",
                schedule.trigger,
                args=[schedule.job_id.removeprefix("eod-")],
                id=schedule.job_id,
                replace_existing=True,
            )
        else:
            scheduler.add_job(
                f"{_MODULE}:run_{schedule.job_id}",
                schedule.trigger,
                id=schedule.job_id,
                replace_existing=True,
            )
    scheduler.add_job(
        f"{_MODULE}:run_notify",
        "interval",
        seconds=NOTIFY_SECONDS,
        id="notify",
        replace_existing=True,
        misfire_grace_time=NOTIFY_SECONDS,
    )
    scheduler.add_job(
        f"{_MODULE}:run_agent_tick",
        "interval",
        seconds=AGENT_SECONDS,
        id="agent",
        replace_existing=True,
        misfire_grace_time=AGENT_SECONDS,
    )
    scheduler.add_job(
        f"{_MODULE}:run_requests",
        "interval",
        seconds=POLL_SECONDS,
        id="job-requests",
        replace_existing=True,
        misfire_grace_time=POLL_SECONDS,
    )
    return scheduler
