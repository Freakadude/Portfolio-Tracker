"""Twelve Data adapter (secondary source).

Its free tier covers US markets only; European listings need a paid plan. Shapes follow the
public documentation and tests use documentation-derived fixtures (see
tests/fixtures/providers/README.md).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from folio.marketdata.base import (
    Bar,
    DividendEvent,
    ListingRef,
    NotSupported,
    ProviderError,
    Quote,
    SearchHit,
    SplitEvent,
    SymbolMeta,
    SymbolNotFound,
)
from folio.marketdata.http import HttpClient, check_status

BASE = "https://api.twelvedata.com"


def _dec(value: Any) -> Decimal | None:
    return None if value in (None, "") else Decimal(str(value))


class TwelveDataProvider:
    name = "twelvedata"

    def __init__(self, http: HttpClient, api_key: str) -> None:
        self._http = http
        self._key = api_key

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        response = self._http.request(
            "GET", f"{BASE}/{path}", params={"apikey": self._key, **params}
        )
        check_status(self.name, response)
        try:
            body: dict[str, Any] = response.json()
        except ValueError as exc:
            raise ProviderError("Twelve Data sent a response that could not be read.") from exc
        if body.get("status") == "error":  # errors arrive as HTTP 200 with a code in the body
            code, message = body.get("code"), body.get("message", "unknown error")
            if code == 404:
                raise SymbolNotFound(f"Twelve Data: {message}")
            raise ProviderError(f"Twelve Data error {code}: {message}")
        return body

    def get_eod(self, listing: ListingRef, start: date, end: date) -> list[Bar]:
        symbol = listing.symbol_for(self.name)
        body = self._get(
            "time_series",
            symbol=symbol,
            interval="1day",
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            order="ASC",
            outputsize=5000,
        )
        bars = [
            Bar(
                date=date.fromisoformat(row["datetime"][:10]),
                close=_dec(row["close"]) or Decimal(0),
                open=_dec(row.get("open")),
                high=_dec(row.get("high")),
                low=_dec(row.get("low")),
                volume=_dec(row.get("volume")),
            )
            for row in body.get("values", [])
            if row.get("close") not in (None, "")
        ]
        return sorted(bars, key=lambda b: b.date)

    def get_quotes(self, listings: Sequence[ListingRef]) -> dict[int, Quote]:
        quotes: dict[int, Quote] = {}
        for listing in listings:
            body = self._get("quote", symbol=listing.symbol_for(self.name))
            close, stamp = _dec(body.get("close")), body.get("timestamp")
            if close is not None and stamp is not None:
                quotes[listing.listing_id] = Quote(close, datetime.fromtimestamp(int(stamp), UTC))
        return quotes

    def get_dividends(self, listing: ListingRef, start: date, end: date) -> list[DividendEvent]:
        raise NotSupported("Twelve Data dividends are not used.")

    def get_splits(self, listing: ListingRef, start: date, end: date) -> list[SplitEvent]:
        raise NotSupported("Twelve Data splits are not used.")

    def probe(self, symbol: str) -> SymbolMeta | None:
        return None

    def search(self, query: str) -> list[SearchHit]:
        raise NotSupported("Twelve Data search is not used.")
