"""Per-provider daily call counting (FR-MD-10) and the circuit breaker (NFR-05)."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from folio.db.models_ledger import ProviderCall
from folio.marketdata.base import BudgetExhausted


def today_utc() -> date:
    return datetime.now(UTC).date()


class UsageTracker:
    """Counts every outgoing call per provider per UTC day and enforces the daily budget.

    The increment is a single conditional UPDATE, so the web process, the worker and parallel
    jobs can never push the count past the limit. A limit of 0 means unlimited.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        limit_for: Callable[[str], int],
        today: Callable[[], date] = today_utc,
    ) -> None:
        self._factory = session_factory
        self._limit_for = limit_for
        self._today = today

    def charge(self, provider: str) -> int:
        """Reserve one call; returns today's count including it. Raises BudgetExhausted."""
        day, limit = self._today(), self._limit_for(provider)
        with self._factory() as db:
            self._ensure_row(db, provider, day)
            stmt = update(ProviderCall).where(
                ProviderCall.provider == provider, ProviderCall.day == day
            )
            if limit > 0:
                stmt = stmt.where(ProviderCall.count < limit)
            result = db.execute(stmt.values(count=ProviderCall.count + 1))
            db.commit()
            if result.rowcount == 0:  # type: ignore[attr-defined]
                raise BudgetExhausted(
                    f"The daily budget of {limit} calls for {provider} is used up. "
                    "It resets at midnight UTC."
                )
            return int(db.scalar(self._count_query(provider, day)) or 0)

    def remaining(self, provider: str) -> int | None:
        """Calls left today, or None when the provider has no daily limit."""
        limit = self._limit_for(provider)
        if limit <= 0:
            return None
        return max(0, limit - self.usage_today().get(provider, 0))

    def usage_today(self) -> dict[str, int]:
        with self._factory() as db:
            rows = db.execute(
                select(ProviderCall.provider, ProviderCall.count).where(
                    ProviderCall.day == self._today()
                )
            )
            return {provider: count for provider, count in rows}

    @staticmethod
    def _count_query(provider: str, day: date):  # type: ignore[no-untyped-def]
        return select(ProviderCall.count).where(
            ProviderCall.provider == provider, ProviderCall.day == day
        )

    @staticmethod
    def _ensure_row(db: Session, provider: str, day: date) -> None:
        if db.scalar(UsageTracker._count_query(provider, day)) is not None:
            return
        try:
            db.add(ProviderCall(provider=provider, day=day, count=0))
            db.commit()
        except IntegrityError:  # another process created it first
            db.rollback()


@dataclass
class CircuitBreaker:
    """Opens after `threshold` consecutive failed calls; lets one trial through after the
    cooldown. While open, callers fail fast instead of hammering a provider that is down."""

    threshold: int = 3
    cooldown: timedelta = timedelta(minutes=15)
    clock: Callable[[], float] = time.monotonic
    failures: int = 0
    opened_at: float | None = None

    def allow(self) -> bool:
        if self.opened_at is None:
            return True
        # After the cooldown the breaker is half-open: one trial call decides.
        return self.clock() - self.opened_at >= self.cooldown.total_seconds()

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = self.clock()

    @property
    def is_open(self) -> bool:
        return self.opened_at is not None and not self.allow()
