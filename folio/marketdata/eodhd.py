"""EODHD adapter (primary price source when an API key is configured).

Response shapes follow EODHD's public documentation. They were NOT recorded from the live API
(no key was available while building); tests use documentation-derived fixtures, flagged in
tests/fixtures/providers/README.md. Check them against a real response once a key exists.
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
    ProviderError,
    Quote,
    SearchHit,
    SplitEvent,
    SymbolMeta,
    SymbolNotFound,
)
from folio.marketdata.http import HttpClient, check_status

BASE = "https://eodhd.com/api"


def _dec(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


class EodhdProvider:
    name = "eodhd"

    def __init__(self, http: HttpClient, api_key: str) -> None:
        self._http = http
        self._key = api_key

    def _get(self, path: str, symbol: str | None = None, **params: Any) -> Any:
        response = self._http.request(
            "GET", f"{BASE}/{path}", params={"api_token": self._key, "fmt": "json", **params}
        )
        if response.status_code == 404:
            raise SymbolNotFound(f"EODHD does not know the symbol {symbol or path}.")
        check_status(self.name, response)
        try:
            return response.json(parse_float=Decimal)
        except ValueError as exc:
            raise ProviderError("EODHD sent a response that could not be read.") from exc

    def get_eod(self, listing: ListingRef, start: date, end: date) -> list[Bar]:
        symbol = listing.symbol_for(self.name)
        rows = self._get(
            f"eod/{symbol}",
            symbol,
            **{"from": start.isoformat(), "to": end.isoformat(), "period": "d"},
        )
        bars = [
            Bar(
                date=date.fromisoformat(row["date"]),
                close=_dec(row["close"]) or Decimal(0),
                open=_dec(row.get("open")),
                high=_dec(row.get("high")),
                low=_dec(row.get("low")),
                adj_close=_dec(row.get("adjusted_close")),
                volume=_dec(row.get("volume")),
            )
            for row in rows
            if row.get("close") is not None
        ]
        return sorted(bars, key=lambda b: b.date)

    def get_quotes(self, listings: Sequence[ListingRef]) -> dict[int, Quote]:
        quotes: dict[int, Quote] = {}
        for listing in listings:
            symbol = listing.symbol_for(self.name)
            row = self._get(f"real-time/{symbol}", symbol)
            close, stamp = _dec(row.get("close")), row.get("timestamp")
            if close is not None and stamp is not None:
                quotes[listing.listing_id] = Quote(close, datetime.fromtimestamp(int(stamp), UTC))
        return quotes

    def get_dividends(self, listing: ListingRef, start: date, end: date) -> list[DividendEvent]:
        symbol = listing.symbol_for(self.name)
        rows = self._get(
            f"div/{symbol}", symbol, **{"from": start.isoformat(), "to": end.isoformat()}
        )
        return sorted(
            (
                DividendEvent(
                    ex_date=date.fromisoformat(row["date"]),
                    amount=_dec(row.get("unadjustedValue", row.get("value"))) or Decimal(0),
                    currency=row.get("currency"),
                )
                for row in rows
            ),
            key=lambda d: d.ex_date,
        )

    def get_splits(self, listing: ListingRef, start: date, end: date) -> list[SplitEvent]:
        symbol = listing.symbol_for(self.name)
        rows = self._get(
            f"splits/{symbol}", symbol, **{"from": start.isoformat(), "to": end.isoformat()}
        )
        events = []
        for row in rows:
            new, old = (Decimal(part) for part in str(row["split"]).split("/"))
            events.append(SplitEvent(ex_date=date.fromisoformat(row["date"]), ratio=new / old))
        return sorted(events, key=lambda s: s.ex_date)

    def probe(self, symbol: str) -> SymbolMeta | None:
        return None  # EODHD states the currency in its search results instead

    def search(self, query: str) -> list[SearchHit]:
        rows = self._get(f"search/{query}", query, limit=15)
        return [
            SearchHit(
                symbol=f"{row['Code']}.{row['Exchange']}",
                name=row.get("Name"),
                exchange_code=row.get("Exchange"),
                currency=row.get("Currency"),
                isin=row.get("ISIN"),
                instrument_type=row.get("Type"),
            )
            for row in rows
        ]
