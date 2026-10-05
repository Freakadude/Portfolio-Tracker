"""The notification worker, every minute: new signals become inbox items, due pushes are sent,
and the daily (and on Sundays the weekly) digest is written once its time has come.

It does not write a job-run row each minute (that would bury the System page); deliveries
have their own log (FR-NT-08), and a crash is logged like any other job error.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.db.models_strategy import Notification
from folio.jobs.context import JobContext
from folio.logging import get_logger
from folio.notify.digest import build_digest
from folio.notify.dispatch import DispatchResult, _hhmm, dispatch
from folio.notify.service import consume_signals, notification_settings
from folio.settings_schema import GeneralSettings
from folio.settings_store import load_section

log = get_logger("folio.notify")


def _digest_due(db: Session, now: datetime, kind: str) -> bool:
    settings = notification_settings(db)
    if not (settings.digest_daily if kind == "daily" else settings.digest_weekly):
        return False
    zone = ZoneInfo(
        GeneralSettings.model_validate(load_section(db, "general").model_dump()).timezone
    )
    local = now.astimezone(zone)
    if kind == "weekly" and local.weekday() != 6:  # Sunday
        return False
    at = _hhmm(settings.digest_daily_time)
    if local.time() < at:
        return False
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(now.tzinfo)
    done = db.scalar(
        select(Notification.id).where(
            Notification.source == "digest",
            Notification.subject == f"{kind} digest",
            Notification.created_at >= midnight,
        )
    )
    return done is None


def notify_job(ctx: JobContext) -> DispatchResult:
    now = ctx.now()
    with ctx.session_factory() as db:
        try:
            created = consume_signals(db, now)
            for kind in ("daily", "weekly"):
                if _digest_due(db, now, kind):
                    build_digest(db, kind, now, ctx.today())
                    created += 1
            db.commit()
            result = dispatch(db, now, ctx.channels_for(db))
            db.commit()
        except Exception:  # noqa: BLE001 - the next minute tries again
            db.rollback()
            log.exception("notification run failed")
            return DispatchResult(errors=["notification run failed"])
    if created or result.sent or result.failed:
        log.info(
            "notifications",
            created=created,
            sent=result.sent,
            held=result.held,
            merged=result.merged,
            failed=result.failed,
        )
    return result
