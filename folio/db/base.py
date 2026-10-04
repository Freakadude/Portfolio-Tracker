from datetime import UTC, datetime

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from folio.db.types import UTCDateTime


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Every table gets id, created_at and updated_at."""

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class SoftDeleteMixin:
    """User-editable records are soft-deleted."""

    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
