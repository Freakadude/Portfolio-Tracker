"""Provider fallback (FR-MD-11): providers are tried in priority order; each result records the
provider that produced it. A provider that fails (after its own retries), is out of budget, is
paused by its circuit breaker, does not know the symbol, or returns nothing when data was
expected is skipped and the next one is tried."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import TypeVar

from folio.logging import get_logger
from folio.marketdata.base import (
    Bar,
    DividendEvent,
    ListingRef,
    PriceProvider,
    ProviderError,
    Quote,
    SplitEvent,
    SymbolMeta,
)

T = TypeVar("T")
log = get_logger("folio.marketdata")


@dataclass(frozen=True)
class FetchResult[T]:
    data: T
    source: str


class AllProvidersFailed(ProviderError):
    def __init__(self, what: str, failures: Mapping[str, str]) -> None:
        self.what = what
        self.failures = dict(failures)
        detail = "; ".join(f"{name}: {reason}" for name, reason in failures.items())
        super().__init__(f"No provider could supply {what}. {detail or 'No provider is enabled.'}")


class ProviderChain:
    def __init__(self, providers: Sequence[PriceProvider]) -> None:
        self.providers = list(providers)

    def _first(
        self,
        what: str,
        call: Callable[[PriceProvider], T],
        accept: Callable[[T], bool] | None = None,
    ) -> FetchResult[T]:
        failures: dict[str, str] = {}
        for provider in self.providers:
            try:
                data = call(provider)
            except ProviderError as exc:
                failures[provider.name] = str(exc)
                log.warning("provider failed", provider=provider.name, what=what, reason=str(exc))
                continue
            if accept is not None and not accept(data):
                failures[provider.name] = "returned no data"
                continue
            return FetchResult(data, provider.name)
        raise AllProvidersFailed(what, failures)

    def get_eod(
        self, listing: ListingRef, start: date, end: date, *, require_bars: bool = False
    ) -> FetchResult[list[Bar]]:
        """`require_bars`: the range contains trading days, so an empty answer (a free plan's
        history limit, for example) counts as a failure and the next provider is asked."""
        return self._first(
            f"closes for {listing.ticker}",
            lambda p: p.get_eod(listing, start, end),
            (lambda bars: bool(bars)) if require_bars else None,
        )

    def get_splits(
        self, listing: ListingRef, start: date, end: date
    ) -> FetchResult[list[SplitEvent]]:
        return self._first(
            f"splits for {listing.ticker}", lambda p: p.get_splits(listing, start, end)
        )

    def get_dividends(
        self, listing: ListingRef, start: date, end: date
    ) -> FetchResult[list[DividendEvent]]:
        return self._first(
            f"dividends for {listing.ticker}", lambda p: p.get_dividends(listing, start, end)
        )

    def get_quotes(self, listings: Sequence[ListingRef]) -> FetchResult[dict[int, Quote]]:
        return self._first("quotes", lambda p: p.get_quotes(listings))

    def probe(self, symbol: str) -> FetchResult[SymbolMeta] | None:
        """Ask the providers, in order, to confirm what they know about a symbol."""
        for provider in self.providers:
            try:
                meta = provider.probe(symbol)
            except ProviderError:
                continue
            if meta is not None:
                return FetchResult(meta, provider.name)
        return None
