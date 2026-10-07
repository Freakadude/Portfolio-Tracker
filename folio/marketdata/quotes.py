"""Delayed intraday quotes for held and watched listings (FR-MD-05).

Quotes are fetched every 15 minutes while an exchange is open, only for what is held or on a
watchlist, and only
within the call budget: a provider is used for quotes only while enough of its daily budget is
left over for the nightly closes. Budget exhaustion therefore pauses quotes and never EOD.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from folio.db.models_analytics import Quote, Watchlist, WatchlistItem
from folio.db.models_ledger import Instrument, Listing, Position
from folio.marketdata import exchanges
from folio.marketdata.base import ListingRef, PriceProvider
from folio.marketdata.budget import UsageTracker
from folio.marketdata.fallback import AllProvidersFailed, ProviderChain
from folio.marketdata.prices import listing_ref

EOD_MARGIN = 5  # calls kept back beyond one per tracked listing: a retry, a gap repair


def held_listings(db: Session) -> list[tuple[Listing, Instrument]]:
    """The pricing listing of every instrument with a positive holding in some account, and of
    every instrument on a watchlist: watched ones are priced like holdings (FR-INS-05)."""
    held: set[int] = set()
    for instrument_id, quantity in db.execute(select(Position.instrument_id, Position.quantity)):
        if quantity > 0:
            held.add(instrument_id)
    held.update(
        db.scalars(
            select(WatchlistItem.instrument_id)
            .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
            .where(Watchlist.deleted_at.is_(None))
        )
    )
    if not held:
        return []
    rows = db.execute(
        select(Listing, Instrument)
        .join(Instrument, Instrument.id == Listing.instrument_id)
        .where(
            Instrument.id.in_(held),
            Listing.pricing_primary.is_(True),
            Instrument.manual.is_(False),
            Instrument.deleted_at.is_(None),
        )
        .order_by(Listing.id)
    )
    return [(listing, instrument) for listing, instrument in rows]


def open_now(
    listings: Sequence[tuple[Listing, Instrument]], now: datetime
) -> list[tuple[Listing, Instrument]]:
    return [
        (listing, instrument)
        for listing, instrument in listings
        if exchanges.has_calendar(listing.exchange_mic)
        and exchanges.is_open(listing.exchange_mic, now)
    ]


@dataclass(frozen=True)
class QuoteSummary:
    stored: int
    source: str | None
    skipped: dict[str, str]  # provider -> why it was not used
    missing: tuple[str, ...] = ()  # tickers the provider that answered had no quote for


class QuoteService:
    def __init__(
        self, db: Session, chain: ProviderChain, usage: UsageTracker | None = None
    ) -> None:
        self._db = db
        self._chain = chain
        self._usage = usage

    def refresh(self, listings: Sequence[ListingRef], now: datetime, reserve: int) -> QuoteSummary:
        """Fetch quotes for `listings` from the first provider with budget to spare: after the
        calls this takes, at least `reserve` must remain for the nightly closes."""
        skipped: dict[str, str] = {}

        def allow(provider: PriceProvider) -> bool:
            if self._usage is None:
                return True
            left = self._usage.remaining(provider.name)
            if left is None or left - len(listings) >= reserve:
                return True
            skipped[provider.name] = (
                f"{left} calls left today; {reserve} are kept for the nightly closes"
            )
            return False

        try:
            result = self._chain.get_quotes(listings, allow=allow)
        except AllProvidersFailed as exc:
            return QuoteSummary(0, None, {**exc.failures, **skipped})
        stored = 0
        for listing_id, quote in result.data.items():
            same = self._db.scalar(
                select(Quote.id).where(Quote.listing_id == listing_id, Quote.ts == quote.ts)
            )
            if same is None:
                self._db.add(
                    Quote(
                        listing_id=listing_id,
                        ts=quote.ts,
                        price=quote.price,
                        source=result.source,
                    )
                )
                stored += 1
        self._db.flush()
        missing = tuple(ref.ticker for ref in listings if ref.listing_id not in result.data)
        return QuoteSummary(stored, result.source, skipped, missing)

    def latest(self, listing_id: int) -> tuple[Decimal, datetime, str] | None:
        row = self._db.scalars(
            select(Quote).where(Quote.listing_id == listing_id).order_by(Quote.ts.desc()).limit(1)
        ).first()
        return None if row is None else (row.price, row.ts, row.source)


def newer_quote(
    db: Session, listing: Listing, close_date: date
) -> tuple[Decimal, datetime, str] | None:
    """The newest quote (price, time, source) when it was made on a later exchange-local day than
    the newest close. Between the close and the nightly fetch that is the last traded price of the
    day; once the close is stored the close wins."""
    row = db.scalars(
        select(Quote).where(Quote.listing_id == listing.id).order_by(Quote.ts.desc()).limit(1)
    ).first()
    if row is None or exchanges.local_date(listing.exchange_mic, row.ts) <= close_date:
        return None
    return row.price, row.ts, row.source


def prune_quotes(db: Session, now: datetime, keep_days: int) -> int:
    result = db.execute(delete(Quote).where(Quote.ts < now - timedelta(days=keep_days)))
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


def listing_refs(
    listings: Sequence[tuple[Listing, Instrument]],
) -> list[ListingRef]:
    return [listing_ref(listing, instrument.isin) for listing, instrument in listings]
