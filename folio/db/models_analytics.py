"""Phase 2 tables: classification, watchlists, delayed quotes, dashboards and live events."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from folio.db.base import Base, SoftDeleteMixin, utcnow
from folio.db.types import DecimalText, UTCDateTime


class Sleeve(Base, SoftDeleteMixin):
    """An owner-defined bucket (for example "us_equity") that strategies and drift refer to.
    Targets and bands are optional (Q3): without a target a sleeve shows no drift."""

    __tablename__ = "sleeve"

    name: Mapped[str] = mapped_column(String(60))
    target_pct: Mapped[Decimal | None] = mapped_column(DecimalText, default=None)
    band_pct: Mapped[Decimal | None] = mapped_column(DecimalText, default=None)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Watchlist(Base, SoftDeleteMixin):
    __tablename__ = "watchlist"

    name: Mapped[str] = mapped_column(String(100))


class WatchlistItem(Base):
    __tablename__ = "watchlist_item"
    __table_args__ = (UniqueConstraint("watchlist_id", "instrument_id"),)

    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlist.id"), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id"))
    note: Mapped[str | None] = mapped_column(Text, default=None)


class Quote(Base):
    """A delayed intraday price (FR-MD-05); pruned after the retention period."""

    __tablename__ = "quote"

    listing_id: Mapped[int] = mapped_column(ForeignKey("listing.id"), index=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    price: Mapped[Decimal] = mapped_column(DecimalText)
    source: Mapped[str] = mapped_column(String(20))


class Dashboard(Base, SoftDeleteMixin):
    __tablename__ = "dashboard"

    name: Mapped[str] = mapped_column(String(100))
    layouts: Mapped[Any] = mapped_column(JSON, default=dict)  # breakpoint -> [{i, x, y, w, h}]
    filters: Mapped[Any] = mapped_column(JSON, default=dict)  # dashboard-level period and account
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Widget(Base):
    __tablename__ = "widget"

    dashboard_id: Mapped[int] = mapped_column(ForeignKey("dashboard.id"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    config: Mapped[Any] = mapped_column(JSON, default=dict)
    grid: Mapped[Any] = mapped_column(JSON, default=dict)  # the desktop position: x, y, w, h


class AppEvent(Base):
    """Written by the worker, streamed to the browser by the web process (server-sent events).
    Rows older than a day are pruned."""

    __tablename__ = "app_event"

    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    type: Mapped[str] = mapped_column(String(30))  # price_update | job_status
    payload: Mapped[Any] = mapped_column(JSON, default=dict)


class MacroSeries(Base):
    """A dated indicator (FR-MD-08): here first the ECB deposit facility rate, used as the
    risk-free rate. Phase 3 adds the FRED series to the same tables."""

    __tablename__ = "macro_series"

    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(20))
    unit: Mapped[str] = mapped_column(String(20), default="percent")


class MacroPoint(Base):
    __tablename__ = "macro_point"
    __table_args__ = (UniqueConstraint("series_id", "date"),)

    series_id: Mapped[int] = mapped_column(ForeignKey("macro_series.id"), index=True)
    date: Mapped[date] = mapped_column(Date)
    value: Mapped[Decimal] = mapped_column(DecimalText)
