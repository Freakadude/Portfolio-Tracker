"""The provider interface (FR-MD-01) and the plain data types every adapter returns.

Valuation code only ever sees these types, so swapping a provider never touches it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol


class ProviderError(Exception):
    """A provider could not answer. The message is safe to show to the owner."""


class NotSupported(ProviderError):
    """This provider does not offer the requested data (try the next one)."""


class SymbolNotFound(ProviderError):
    """The provider does not know this symbol."""


class BudgetExhausted(ProviderError):
    """The daily call budget for this provider is used up (FR-MD-10)."""


class ProviderUnavailable(ProviderError):
    """The circuit breaker is open: the provider failed repeatedly and is being left alone."""


@dataclass(frozen=True)
class ListingRef:
    """What an adapter needs to know about one listing."""

    listing_id: int
    exchange_mic: str
    ticker: str
    currency: str
    provider_symbols: Mapping[str, str] = field(default_factory=dict)
    isin: str | None = None

    def symbol_for(self, provider: str) -> str:
        symbol = self.provider_symbols.get(provider)
        if not symbol:
            raise SymbolNotFound(
                f"No {provider} symbol is known for {self.ticker} ({self.exchange_mic})."
            )
        return symbol


@dataclass(frozen=True)
class Bar:
    date: date  # exchange-local trading date
    close: Decimal
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    adj_close: Decimal | None = None
    volume: Decimal | None = None


@dataclass(frozen=True)
class DividendEvent:
    ex_date: date
    amount: Decimal  # per unit, in `currency`
    currency: str | None = None


@dataclass(frozen=True)
class SplitEvent:
    ex_date: date
    ratio: Decimal  # new units per old unit: 4 for a 4-for-1, 0.5 for a 1-for-2 reverse split


@dataclass(frozen=True)
class Quote:
    price: Decimal
    ts: datetime  # UTC


@dataclass(frozen=True)
class SymbolMeta:
    """Facts a provider can state about a symbol, used to confirm the trading currency."""

    symbol: str
    currency: str
    exchange_name: str | None = None
    timezone: str | None = None
    instrument_type: str | None = None


@dataclass(frozen=True)
class SearchHit:
    symbol: str
    name: str | None = None
    exchange_code: str | None = None
    currency: str | None = None
    isin: str | None = None
    instrument_type: str | None = None


class PriceProvider(Protocol):
    """Every method may raise ProviderError (or a subclass); NotSupported means "ask another"."""

    name: str

    def search(self, query: str) -> list[SearchHit]: ...

    def get_eod(self, listing: ListingRef, start: date, end: date) -> list[Bar]: ...

    def get_quotes(self, listings: Sequence[ListingRef]) -> dict[int, Quote]: ...

    def get_dividends(self, listing: ListingRef, start: date, end: date) -> list[DividendEvent]: ...

    def get_splits(self, listing: ListingRef, start: date, end: date) -> list[SplitEvent]: ...

    def probe(self, symbol: str) -> SymbolMeta | None: ...
