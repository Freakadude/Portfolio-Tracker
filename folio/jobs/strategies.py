"""The rules job (FR-ST-03): evaluates the active strategy and every shadow strategy and stores
the signals that should fire. It runs after the nightly closes, after macro updates, after any
transaction change (queued by the ledger service) and on demand."""

from __future__ import annotations

from sqlalchemy.orm import Session

from folio.jobs.context import JobContext
from folio.jobs.runner import JobLog, JobResult, run_job
from folio.notify.alerts import evaluate_alerts
from folio.notify.service import consume_signals
from folio.strategies import service
from folio.strategies.inputs import build
from folio.strategies.rules import evaluate
from folio.strategies.signals import record


def rules_job(ctx: JobContext) -> JobResult:
    def body(db: Session, log: JobLog) -> None:
        today, now = ctx.today(), ctx.now()
        alerts = evaluate_alerts(db, now)
        if alerts:
            log.info(f"{len(alerts)} price alert(s) fired")
        running = service.running(db)
        if not running:
            log.info("No active or shadow strategy; nothing to check.")
        for strategy, version, definition in running:
            inputs = build(db, definition, today, version.created_at.date())
            evaluation = evaluate(definition, inputs)
            fired = record(db, strategy, version, definition, evaluation, now)
            waiting = sum(1 for s in evaluation.statuses if not s.ready)
            log.info(
                f"{strategy.name} ({strategy.mode}, v{version.version}): "
                f"{len(evaluation.findings)} condition(s) true, {len(fired)} new signal(s), "
                f"{waiting} rule(s) waiting for data or numbers"
            )

        notified = consume_signals(db, now)  # the inbox shows them at once
        if notified:
            log.info(f"{notified} new item(s) in the inbox")

    return run_job(ctx, "rules", body)
