"""Daily closes: storing, backfilling, gap detection, staleness and manual overrides
(FR-MD-03, FR-MD-04, FR-MD-11, FR-INS-02)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from folio.audit import write_audit
from folio.db.models_ledger import Instrument, Listing, PriceBar
from folio.marketdata import exchanges
from folio.marketdata.base import Bar, ListingRef
from folio.marketdata.fallback import ProviderChain

STALE_AFTER_TRADING_DAYS = 3
RECENT_WINDOW_DAYS = 10  # how far back a nightly update looks when it has no stored bars
MANUAL = "manual"


def listing_ref(listing: Listing, isin: str | None = None) -> ListingRef:
    return ListingRef(
        listing_id=listing.id,
        exchange_mic=listing.exchange_mic,
        ticker=listing.ticker,
        currency=listing.currency,
        provider_symbols=dict(listing.provider_symbols or {}),
        isin=isin,
    )


@dataclass(frozen=True)
class FetchSummary:
    listing_id: int
    source: str | None
    stored: int
    requested: tuple[date, date] | None


class PriceService:
    def __init__(self, db: Session, chain: ProviderChain | None = None) -> None:
        self._db = db
        self._chain = chain

    # --- reading --------------------------------------------------------------------------------

    def last_bar(self, listing_id: int, on: date | None = None) -> PriceBar | None:
        query = select(PriceBar).where(PriceBar.listing_id == listing_id)
        if on is not None:
            query = query.where(PriceBar.date <= on)
        return self._db.scalars(query.order_by(PriceBar.date.desc()).limit(1)).first()

    def stored_dates(self, listing_id: int, start: date, end: date) -> set[date]:
        rows = self._db.scalars(
            select(PriceBar.date).where(
                PriceBar.listing_id == listing_id, PriceBar.date >= start, PriceBar.date <= end
            )
        )
        return set(rows)

    def first_date(self, listing_id: int) -> date | None:
        return self._db.scalar(
            select(func.min(PriceBar.date)).where(PriceBar.listing_id == listing_id)
        )

    # --- writing --------------------------------------------------------------------------------

    def store_bars(self, listing_id: int, bars: Iterable[Bar], source: str) -> int:
        """Insert or refresh bars (idempotent). A bar the owner overrode is never replaced by a
        fetched one. Returns the number of rows added or changed."""
        bars = list(bars)
        if not bars:
            return 0
        existing = {
            row.date: row
            for row in self._db.scalars(
                select(PriceBar).where(
                    PriceBar.listing_id == listing_id,
                    PriceBar.date >= min(b.date for b in bars),
                    PriceBar.date <= max(b.date for b in bars),
                )
            )
        }
        changed = 0
        for bar in bars:
            row = existing.get(bar.date)
            if row is None:
                self._db.add(
                    PriceBar(
                        listing_id=listing_id,
                        date=bar.date,
                        open=bar.open,
                        high=bar.high,
                        low=bar.low,
                        close=bar.close,
                        adj_close=bar.adj_close,
                        volume=bar.volume,
                        source=source,
                    )
                )
                changed += 1
            elif not row.overridden and (row.close != bar.close or row.source != source):
                row.open, row.high, row.low = bar.open, bar.high, bar.low
                row.close, row.adj_close, row.volume = bar.close, bar.adj_close, bar.volume
                row.source = source
                changed += 1
        self._db.flush()
        return changed

    def set_manual_price(
        self, listing_id: int, day: date, close: Decimal, actor: str = "user"
    ) -> PriceBar:
        """Enter or override a close by hand. The change is audited with the old and new value
        and the bar is protected from being overwritten by later fetches (FR-MD-04)."""
        if close <= 0:
            raise ValueError("A price must be greater than zero.")
        row = self._db.scalar(
            select(PriceBar).where(PriceBar.listing_id == listing_id, PriceBar.date == day)
        )
        old = None if row is None else {"close": str(row.close), "source": row.source}
        if row is None:
            row = PriceBar(listing_id=listing_id, date=day, close=close, source=MANUAL)
            self._db.add(row)
        else:
            row.close, row.source = close, MANUAL
        row.overridden = True
        self._db.flush()
        write_audit(
            self._db,
            actor,
            "price_bar",
            "override" if old else "create",
            entity_id=f"{listing_id}:{day.isoformat()}",
            diff={"close": {"old": old["close"] if old else None, "new": str(close)}},
        )
        return row

    # --- fetching -------------------------------------------------------------------------------

    def _fetch(self, ref: ListingRef, start: date, end: date) -> FetchSummary:
        if self._chain is None:
            raise RuntimeError("PriceService needs a provider chain to fetch prices")
        if exchanges.has_calendar(ref.exchange_mic):
            expect_data = bool(exchanges.trading_days(ref.exchange_mic, start, end))
            if not expect_data:  # a weekend or holiday window: nothing to ask for
                return FetchSummary(ref.listing_id, None, 0, None)
        else:
            expect_data = True
        result = self._chain.get_eod(ref, start, end, require_bars=expect_data)
        stored = self.store_bars(ref.listing_id, result.data, result.source)
        return FetchSummary(ref.listing_id, result.source, stored, (start, end))

    def backfill(self, ref: ListingRef, start: date, end: date) -> FetchSummary:
        """History from `start` (the first transaction date) to `end` (FR-MD-03)."""
        return self._fetch(ref, start, end)

    def update_latest(self, ref: ListingRef, today: date) -> FetchSummary:
        """Fetch everything after the newest stored close (or the recent past if none)."""
        last = self.last_bar(ref.listing_id)
        start = (
            last.date + timedelta(days=1) if last else today - timedelta(days=RECENT_WINDOW_DAYS)
        )
        if start > today:
            return FetchSummary(ref.listing_id, None, 0, None)
        return self._fetch(ref, start, today)

    # --- gaps and staleness ---------------------------------------------------------------------

    def detect_gaps(
        self, ref: ListingRef, start: date | None = None, end: date | None = None
    ) -> list[date]:
        """Trading days with no stored close between the first and last stored bar (FR-MD-04)."""
        if not exchanges.has_calendar(ref.exchange_mic):
            return []  # hand-priced listings have no trading calendar
        first_stored = self.first_date(ref.listing_id)
        last_bar = self.last_bar(ref.listing_id)
        if first_stored is None or last_bar is None:
            return []
        # Days before the first stored close are missing history, not gaps.
        first = max(start, first_stored) if start else first_stored
        until = min(end, last_bar.date) if end else last_bar.date
        expected = exchanges.trading_days(ref.exchange_mic, first, until)
        have = self.stored_dates(ref.listing_id, first, until)
        return [d for d in expected if d not in have]

    def fill_gaps(
        self, ref: ListingRef, start: date | None = None, end: date | None = None
    ) -> list[date]:
        """Refetch the span covering the gaps; returns the gaps that remain afterwards."""
        gaps = self.detect_gaps(ref, start, end)
        if not gaps:
            return []
        self._fetch(ref, gaps[0], gaps[-1])
        return self.detect_gaps(ref, start, end)

    def is_stale(self, ref: ListingRef, today: date) -> bool:
        """Stale = the newest close is more than 3 trading days old (FR-MD-11). Hand-priced
        listings are never flagged: the owner maintains those."""
        if not exchanges.has_calendar(ref.exchange_mic):
            return False
        last = self.last_bar(ref.listing_id, today)
        if last is None:
            return True
        behind = exchanges.trading_days(ref.exchange_mic, last.date + timedelta(days=1), today)
        return len(behind) > STALE_AFTER_TRADING_DAYS


def tracked_listings(db: Session, mic: str | None = None) -> list[tuple[Listing, Instrument]]:
    """Primary listings of active instruments that are priced by a provider."""
    query = (
        select(Listing, Instrument)
        .join(Instrument, Instrument.id == Listing.instrument_id)
        .where(
            Listing.pricing_primary.is_(True),
            Instrument.status == "active",
            Instrument.deleted_at.is_(None),
            Instrument.manual.is_(False),
        )
        .order_by(Listing.id)
    )
    if mic is not None:
        query = query.where(Listing.exchange_mic == mic)
    return [(listing, instrument) for listing, instrument in db.execute(query)]
