"""Stored indicator series (FR-MD-08 groundwork). The first one is the ECB deposit facility rate,
the default risk-free rate for the Sharpe ratio (FR-PF-06)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from folio.db.models_analytics import MacroPoint, MacroSeries
from folio.marketdata.ecb import EcbRates

DEPOSIT_RATE = "ECB_DFR"
_OVERLAP = timedelta(days=7)  # re-fetched so a late revision is picked up


class MacroService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def series(self, code: str, name: str, source: str, unit: str = "percent") -> MacroSeries:
        found = self._db.scalar(select(MacroSeries).where(MacroSeries.code == code))
        if found is None:
            found = MacroSeries(code=code, name=name, source=source, unit=unit)
            self._db.add(found)
            self._db.flush()
        return found

    def store(self, series: MacroSeries, points: Iterable[tuple[date, Decimal]]) -> int:
        """Insert or refresh dated values (idempotent). Returns how many rows were added or
        changed."""
        points = list(dict(points).items())  # one value per day: the last one wins
        if not points:
            return 0
        existing = {
            row.date: row
            for row in self._db.scalars(
                select(MacroPoint).where(
                    MacroPoint.series_id == series.id,
                    MacroPoint.date >= min(d for d, _ in points),
                    MacroPoint.date <= max(d for d, _ in points),
                )
            )
        }
        changed = 0
        for day, value in points:
            row = existing.get(day)
            if row is None:
                self._db.add(MacroPoint(series_id=series.id, date=day, value=value))
                changed += 1
            elif row.value != value:
                row.value = value
                changed += 1
        self._db.flush()
        return changed

    def latest_date(self, code: str) -> date | None:
        return self._db.scalar(
            select(func.max(MacroPoint.date))
            .join(MacroSeries, MacroSeries.id == MacroPoint.series_id)
            .where(MacroSeries.code == code)
        )

    def value_on(self, code: str, day: date) -> Decimal | None:
        """The latest value on or before `day`."""
        return self._db.scalar(
            select(MacroPoint.value)
            .join(MacroSeries, MacroSeries.id == MacroPoint.series_id)
            .where(MacroSeries.code == code, MacroPoint.date <= day)
            .order_by(MacroPoint.date.desc())
            .limit(1)
        )

    def update_deposit_rate(self, ecb: EcbRates, today: date, floor: date) -> int:
        """Fetch what is missing of the ECB deposit facility rate (percent). The fetch comes
        first and the writes after it: a call counted against the budget uses another database
        connection, which must not find this one holding the write lock."""
        last = self.latest_date(DEPOSIT_RATE)
        start = floor if last is None else max(floor, last - _OVERLAP)
        points = ecb.deposit_rate(start, today)
        series = self.series(DEPOSIT_RATE, "ECB deposit facility rate", "ecb", unit="percent")
        return self.store(series, points)
