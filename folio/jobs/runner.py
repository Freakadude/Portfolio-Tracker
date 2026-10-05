"""Runs one job: records a `job_run` row with its log and outcome, and gives the log lines a job
ID so they can be found again (NFR-09)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from folio.db.base import utcnow
from folio.db.models_ledger import JobRun
from folio.events import JOB_STATUS, publish_event
from folio.jobs.context import JobContext
from folio.logging import correlation_id, get_logger

log = get_logger("folio.jobs")


@dataclass
class JobLog:
    """Lines shown on the System page. Any error line marks the run as failed, even when the
    rest of the work succeeded (one bad listing must not hide behind the others)."""

    lines: list[str] = field(default_factory=list)
    failed: bool = False

    def info(self, message: str) -> None:
        self.lines.append(message)

    def error(self, message: str) -> None:
        self.failed = True
        self.lines.append(f"ERROR {message}")


@dataclass(frozen=True)
class JobResult:
    run_id: int
    job: str
    status: str  # ok | failed
    log: str


def run_job(
    ctx: JobContext,
    name: str,
    body: Callable[[Session, JobLog], None],
    params: dict[str, Any] | None = None,
) -> JobResult:
    with ctx.session_factory() as db:
        run = JobRun(job=name, params=params or {}, started_at=ctx.now())
        db.add(run)
        db.commit()
        run_id = run.id

    token = correlation_id.set(f"job-{run_id}")
    job_log = JobLog()
    status = "ok"
    try:
        with ctx.session_factory() as db:
            try:
                body(db, job_log)
                db.commit()
            except Exception as exc:  # noqa: BLE001 - a job must never take the worker down
                db.rollback()
                job_log.error(f"{type(exc).__name__}: {exc}")
                log.exception("job failed", job=name)
        if job_log.failed:
            status = "failed"
    finally:
        correlation_id.reset(token)

    with ctx.session_factory() as db:
        row = db.get(JobRun, run_id)
        if row is not None:
            row.status = status
            row.finished_at = ctx.now()
            row.log = "\n".join(job_log.lines)
            publish_event(db, JOB_STATUS, {"job": name, "status": status, "run_id": run_id})
            db.commit()
    log.info("job finished", job=name, status=status, run_id=run_id)
    return JobResult(run_id, name, status, "\n".join(job_log.lines))


__all__ = ["JobLog", "JobResult", "run_job", "utcnow"]
