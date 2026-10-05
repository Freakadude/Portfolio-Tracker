from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from folio.db.base import Base, SoftDeleteMixin, utcnow
from folio.db.types import UTCDateTime


class User(Base):
    __tablename__ = "app_user"

    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    totp_secret_enc: Mapped[str | None] = mapped_column(Text, default=None)


class UserSession(Base):
    __tablename__ = "user_session"

    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    remember: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class LoginAttempt(Base):
    """Failed logins, persisted so a restart does not reset the throttle."""

    __tablename__ = "login_attempt"
    __table_args__ = (Index("ix_login_attempt_key_ts", "key", "ts"),)

    key: Mapped[str] = mapped_column(String(200))
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Setting(Base):
    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(100), unique=True)
    value: Mapped[Any] = mapped_column(JSON)


class Secret(Base):
    """Provider keys and tokens, encrypted at rest (FR-SY-05)."""

    __tablename__ = "secret"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    ciphertext: Mapped[str] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"Secret(name={self.name!r}, ciphertext=<redacted>)"


class AuditLog(Base):
    """Append-only (FR-SY-08)."""

    __tablename__ = "audit_log"

    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(20))
    entity: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str | None] = mapped_column(String(50), default=None)
    action: Mapped[str] = mapped_column(String(50))
    diff: Mapped[Any] = mapped_column(JSON, default=None)


class Account(Base, SoftDeleteMixin):
    __tablename__ = "account"

    name: Mapped[str] = mapped_column(String(100))
    broker: Mapped[str | None] = mapped_column(String(100), default=None)
    cost_basis_method: Mapped[str] = mapped_column(String(10), default="FIFO")
    base_currency: Mapped[str] = mapped_column(String(3), default="EUR")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    track_cash: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")  # FR-TX-09


# Registers the Phase 1 tables on Base.metadata (Alembic and tests import this module).
from folio.db import models_analytics, models_ledger  # noqa: E402, F401
