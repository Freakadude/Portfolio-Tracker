"""An in-memory provider for tests: drives every job without network (FR-MD-01)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from folio.marketdata.base import (
    Bar,
    DividendEvent,
    ListingRef,
    ProviderError,
    Quote,
    SearchHit,
    SplitEvent,
    SymbolMeta,
)


@dataclass
class FakeProvider:
    name: str = "fake"
    bars: Mapping[int, Sequence[Bar]] = field(default_factory=dict)  # by listing id
    splits: Mapping[int, Sequence[SplitEvent]] = field(default_factory=dict)
    dividends: Mapping[int, Sequence[DividendEvent]] = field(default_factory=dict)
    quotes: Mapping[int, Quote] = field(default_factory=dict)
    currencies: Mapping[str, str] = field(default_factory=dict)  # symbol -> currency for probe
    error: Exception | None = None  # raised by every call when set ("kill the adapter")
    calls: list[tuple[str, int | str]] = field(default_factory=list)
    ranges: list[tuple[date, date]] = field(default_factory=list)  # (start, end) of each get_eod

    def _enter(self, op: str, key: int | str) -> None:
        self.calls.append((op, key))
        if self.error is not None:
            raise self.error

    def get_eod(self, listing: ListingRef, start: date, end: date) -> list[Bar]:
        self._enter("eod", listing.listing_id)
        self.ranges.append((start, end))
        return [b for b in self.bars.get(listing.listing_id, ()) if start <= b.date <= end]

    def get_quotes(self, listings: Sequence[ListingRef]) -> dict[int, Quote]:
        self._enter("quotes", len(listings))
        return {
            x.listing_id: self.quotes[x.listing_id] for x in listings if x.listing_id in self.quotes
        }

    def get_dividends(self, listing: ListingRef, start: date, end: date) -> list[DividendEvent]:
        self._enter("dividends", listing.listing_id)
        return [d for d in self.dividends.get(listing.listing_id, ()) if start <= d.ex_date <= end]

    def get_splits(self, listing: ListingRef, start: date, end: date) -> list[SplitEvent]:
        self._enter("splits", listing.listing_id)
        return [s for s in self.splits.get(listing.listing_id, ()) if start <= s.ex_date <= end]

    def probe(self, symbol: str) -> SymbolMeta | None:
        self._enter("probe", symbol)
        currency = self.currencies.get(symbol)
        return None if currency is None else SymbolMeta(symbol=symbol, currency=currency)

    def search(self, query: str) -> list[SearchHit]:
        self._enter("search", query)
        return []


def make_bars(start: date, closes: Sequence[str]) -> list[Bar]:
    """Consecutive calendar days of closes, for tests that do not care about weekends."""
    from datetime import timedelta

    return [Bar(date=start + timedelta(days=i), close=Decimal(c)) for i, c in enumerate(closes)]


__all__ = ["FakeProvider", "ProviderError", "make_bars"]
