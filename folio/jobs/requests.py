"""User actions that need the worker are queued here; the worker polls every 5 seconds."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from folio.db.models_ledger import JobRequest


def enqueue(db: Session, job: str, params: dict[str, Any] | None = None) -> JobRequest:
    request = JobRequest(job=job, params=params or {})
    db.add(request)
    db.flush()
    return request
