"""User actions that need the worker are queued here; the worker polls every 5 seconds."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.db.models_ledger import JobRequest


def enqueue(db: Session, job: str, params: dict[str, Any] | None = None) -> JobRequest:
    request = JobRequest(job=job, params=params or {})
    db.add(request)
    db.flush()
    return request


def enqueue_once(db: Session, job: str) -> None:
    """Queue a job unless one is already waiting (a batch of edits needs only one run)."""
    waiting = db.scalar(
        select(JobRequest.id).where(JobRequest.job == job, JobRequest.status == "pending")
    )
    if waiting is None:
        enqueue(db, job)


def request_rules(db: Session) -> None:
    """A change can move a sleeve out of its band (FR-ST-03): check the rules soon."""
    enqueue_once(db, "rules")
