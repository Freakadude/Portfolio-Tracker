"""Phase 3 tables: strategies and their versions, signals, price alerts and notifications."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from folio.db.base import Base, SoftDeleteMixin, utcnow
from folio.db.types import DecimalText, UTCDateTime


class Strategy(Base, SoftDeleteMixin):
    """A named strategy. At most one is `active`; `shadow` ones are evaluated and logged but
    never notify (FR-ST-02)."""

    __tablename__ = "strategy"

    name: Mapped[str] = mapped_column(String(100))
    mode: Mapped[str] = mapped_column(String(10), default="off")  # active | shadow | off


class StrategyVersion(Base):
    """One saved version of a strategy. Versions are immutable: a save always adds a row."""

    __tablename__ = "strategy_version"
    __table_args__ = (UniqueConstraint("strategy_id", "version"),)

    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategy.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    yaml: Mapped[str] = mapped_column(Text)  # as the owner wrote it, comments included
    definition: Mapped[Any] = mapped_column(JSON)  # the validated, parsed form
    note: Mapped[str | None] = mapped_column(String(200), default=None)


class Signal(Base):
    """A rule that fired (or would have, for a shadow strategy). A price alert is a signal
    without a strategy version."""

    __tablename__ = "signal"

    strategy_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("strategy_version.id"), default=None, index=True
    )
    rule_id: Mapped[str] = mapped_column(String(60))
    rule_type: Mapped[str] = mapped_column(String(30))
    subject: Mapped[str] = mapped_column(String(120))
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    severity: Mapped[str] = mapped_column(String(10))  # info | low | medium | high | critical
    message: Mapped[str] = mapped_column(Text)
    value: Mapped[Decimal | None] = mapped_column(DecimalText, default=None)
    payload: Mapped[Any] = mapped_column(JSON, default=dict)
    dedup_key: Mapped[str] = mapped_column(String(200), index=True)
    state: Mapped[str] = mapped_column(String(12), default="new")  # new | consumed | suppressed
    shadow: Mapped[bool] = mapped_column(Boolean, default=False)


class PriceAlert(Base, SoftDeleteMixin):
    """A simple owner alert: tell me when this instrument closes above or below a price. It
    fires once on crossing and re-arms when the price is back on the other side."""

    __tablename__ = "price_alert"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id"), index=True)
    condition: Mapped[str] = mapped_column(String(6))  # above | below
    threshold: Mapped[Decimal] = mapped_column(DecimalText)
    note: Mapped[str | None] = mapped_column(String(200), default=None)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    armed: Mapped[bool] = mapped_column(Boolean, default=True)
    last_fired_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


class Notification(Base):
    """An inbox item, the single source of truth for everything Folio tells the owner. The
    push text is written without amounts (and, if asked, without names) for the lock screen."""

    __tablename__ = "notification"

    source: Mapped[str] = mapped_column(String(12))  # signal | alert | system | digest
    subject: Mapped[str] = mapped_column(String(120), index=True)
    severity: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    push_title: Mapped[str] = mapped_column(String(200))
    push_body: Mapped[str] = mapped_column(String(400))
    push_body_anonymous: Mapped[str] = mapped_column(String(400))
    link: Mapped[str | None] = mapped_column(String(300), default=None)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signal.id"), default=None)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


class NotificationDelivery(Base):
    """One notification on one channel: queued, held (quiet hours, cap or hourly batch),
    sent, failed after retries, skipped (channel not set up) or merged into another push."""

    __tablename__ = "notification_delivery"

    notification_id: Mapped[int] = mapped_column(ForeignKey("notification.id"), index=True)
    channel: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(10), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    merged_into_id: Mapped[int | None] = mapped_column(Integer, default=None)
