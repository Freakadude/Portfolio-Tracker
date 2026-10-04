"""Portfolio snapshot jobs (FR-PF-10, FR-TX-06)."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from folio.db.models_ledger import PortfolioSnapshot
from folio.jobs.context import JobContext
from folio.jobs.runner import JobLog, JobResult, run_job
from folio.portfolio import Valuation, lock_closed_years, save_snapshots

NIGHTLY_LOOKBACK_DAYS = 7  # late closes and fixes change the last few days


def snapshots_job(ctx: JobContext, from_date: date | None = None) -> JobResult:
    """Write the daily snapshots. Without `from_date` (the nightly run) it fills everything
    missing and refreshes the last week; with it (queued after a ledger edit, FR-TX-06) it
    redoes every day from that date, so a backdated buy changes the history."""

    def body(db: Session, log: JobLog) -> None:
        today = ctx.today()
        valuation = Valuation.load(db)
        first = valuation.first_date()
        if first is None:
            log.info("No transactions yet; nothing to snapshot.")
            return
        if from_date is not None:
            start = from_date
        else:
            latest = db.scalar(select(func.max(PortfolioSnapshot.date)))
            start = first if latest is None else latest - timedelta(days=NIGHTLY_LOOKBACK_DAYS)
        written = save_snapshots(db, valuation, start, today, today)
        locked = lock_closed_years(db, today)
        log.info(f"{written} snapshot day(s) written from {max(start, first).isoformat()}")
        if locked:
            log.info(f"{locked} peildatum snapshot(s) locked")

    params = {"from": from_date.isoformat()} if from_date else {}
    return run_job(ctx, "snapshots", body, params)
