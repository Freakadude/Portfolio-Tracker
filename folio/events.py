"""Live-update events (FR-DB-04). The worker writes one row when new data lands; the web
process streams new rows to the browser (server-sent events), because the two are separate
processes and share nothing but the database."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from folio.db.base import utcnow
from folio.db.models_analytics import AppEvent

PRICE_UPDATE = "price_update"
JOB_STATUS = "job_status"
RECOMMENDATION = "recommendation"
KEEP = timedelta(days=1)


def publish_event(db: Session, kind: str, payload: dict[str, Any] | None = None) -> AppEvent:
    event = AppEvent(type=kind, payload=payload or {})
    db.add(event)
    db.flush()
    return event


def latest_event_id(db: Session) -> int:
    return db.scalar(select(func.max(AppEvent.id))) or 0


def events_after(db: Session, last_id: int, limit: int = 100) -> list[AppEvent]:
    return list(
        db.scalars(select(AppEvent).where(AppEvent.id > last_id).order_by(AppEvent.id).limit(limit))
    )


def prune_events(db: Session, now: datetime | None = None) -> int:
    cutoff = (now or utcnow()) - KEEP
    result = db.execute(delete(AppEvent).where(AppEvent.ts < cutoff))
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
