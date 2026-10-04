import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from folio.db.base import utcnow
from folio.db.models import User, UserSession

REMEMBER_TTL = timedelta(days=30)
IDLE_TTL = timedelta(hours=12)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User, remember: bool) -> tuple[str, datetime]:
    """Returns the raw token (only ever sent to the browser) and its expiry."""
    token = secrets.token_urlsafe(32)
    expires = utcnow() + (REMEMBER_TTL if remember else IDLE_TTL)
    db.add(
        UserSession(user_id=user.id, token_hash=_hash(token), remember=remember, expires_at=expires)
    )
    db.execute(delete(UserSession).where(UserSession.expires_at <= utcnow()))
    return token, expires


def resolve_session(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    now = utcnow()
    row = db.scalar(select(UserSession).where(UserSession.token_hash == _hash(token)))
    if row is None or row.expires_at <= now:
        return None
    if not row.remember:  # idle sessions slide; remembered devices keep their fixed 30 days
        row.expires_at = now + IDLE_TTL
    row.last_seen_at = now
    return db.get(User, row.user_id)


def end_session(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(UserSession).where(UserSession.token_hash == _hash(token)))
