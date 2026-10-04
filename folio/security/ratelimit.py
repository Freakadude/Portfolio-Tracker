from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from folio.db.base import utcnow
from folio.db.models import LoginAttempt

MAX_FAILURES = 5
WINDOW = timedelta(minutes=15)


def _keys(ip: str, username: str) -> list[str]:
    return [f"ip:{ip}", f"user:{username}"]


def retry_after(db: Session, ip: str, username: str, now: datetime | None = None) -> int | None:
    """Seconds until another login attempt is allowed, or None if the caller is not throttled."""
    now = now or utcnow()
    cutoff = now - WINDOW
    for key in _keys(ip, username):
        count, oldest = db.execute(
            select(func.count(), func.min(LoginAttempt.ts)).where(
                LoginAttempt.key == key, LoginAttempt.ts > cutoff
            )
        ).one()
        if count >= MAX_FAILURES:
            oldest_utc = oldest.replace(tzinfo=now.tzinfo) if oldest.tzinfo is None else oldest
            return max(1, int((oldest_utc + WINDOW - now).total_seconds()) + 1)
    return None


def record_failure(db: Session, ip: str, username: str, now: datetime | None = None) -> None:
    now = now or utcnow()
    db.execute(delete(LoginAttempt).where(LoginAttempt.ts <= now - WINDOW))
    for key in _keys(ip, username):
        db.add(LoginAttempt(key=key, ts=now))


def clear(db: Session, ip: str, username: str) -> None:
    db.execute(delete(LoginAttempt).where(LoginAttempt.key.in_(_keys(ip, username))))
