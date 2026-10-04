"""Yahoo Finance chart API (unofficial; enabled by default per the owner's choice, ADR 0006).

Built against responses recorded from the live API (tests/fixtures/providers/yahoo_*.json).
Yahoo returns binary-float artefacts such as 454.19000244140625; prices are rounded to four
decimals. The API can change without notice, which is why every bar records its source and a
stale-price marker exists.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any
from zoneinfo import ZoneInfo

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

BASE = "https://query1.finance.yahoo.com"
SEARCH_BASE = "https://query2.finance.yahoo.com"
_PRICE_QUANTUM = Decimal("0.0001")


def _price(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(_PRICE_QUANTUM, ROUND_HALF_EVEN)


def _local_date(ts: int, tz_name: str | None) -> date:
    tz = ZoneInfo(tz_name) if tz_name else UTC
    return datetime.fromtimestamp(ts, tz).date()


def _epoch(day: date) -> int:
    return int(datetime.combine(day, time.min, tzinfo=UTC).timestamp())


class YahooProvider:
    name = "yahoo"

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def _chart(self, symbol: str, **params: Any) -> dict[str, Any]:
        response = self._http.request(
            "GET", f"{BASE}/v8/finance/chart/{symbol}", params={"interval": "1d", **params}
        )
        if response.status_code == 404:
            raise SymbolNotFound(f"Yahoo does not know the symbol {symbol}.")
        check_status(self.name, response)
        try:
            chart = response.json()["chart"]
        except (ValueError, KeyError) as exc:
            raise ProviderError("Yahoo sent a response that could not be read.") from exc
        if chart.get("error"):
            description = chart["error"].get("description", "unknown error")
            raise SymbolNotFound(f"Yahoo has no data for {symbol}: {description}")
        results = chart.get("result") or []
        if not results:
            raise SymbolNotFound(f"Yahoo has no data for {symbol}.")
        result: dict[str, Any] = results[0]
        return result

    def get_eod(self, listing: ListingRef, start: date, end: date) -> list[Bar]:
        symbol = listing.symbol_for(self.name)
        result = self._chart(symbol, period1=_epoch(start), period2=_epoch(end + timedelta(days=1)))
        tz_name = result.get("meta", {}).get("exchangeTimezoneName")
        stamps: list[int] = result.get("timestamp") or []
        indicators = result.get("indicators", {})
        quote = (indicators.get("quote") or [{}])[0]
        adj = ((indicators.get("adjclose") or [{}])[0]).get("adjclose") or []
        bars: list[Bar] = []
        for i, stamp in enumerate(stamps):
            close = _price(_at(quote.get("close"), i))
            if close is None:  # a holiday or an unfinished session: no close
                continue
            bars.append(
                Bar(
                    date=_local_date(stamp, tz_name),
                    close=close,
                    open=_price(_at(quote.get("open"), i)),
                    high=_price(_at(quote.get("high"), i)),
                    low=_price(_at(quote.get("low"), i)),
                    adj_close=_price(_at(adj, i)),
                    volume=_volume(_at(quote.get("volume"), i)),
                )
            )
        return bars

    def get_quotes(self, listings: Sequence[ListingRef]) -> dict[int, Quote]:
        quotes: dict[int, Quote] = {}
        for listing in listings:
            result = self._chart(listing.symbol_for(self.name), range="1d")
            meta = result.get("meta", {})
            price, ts = meta.get("regularMarketPrice"), meta.get("regularMarketTime")
            if price is not None and ts is not None:
                quotes[listing.listing_id] = Quote(
                    price=_price(price) or Decimal(0), ts=datetime.fromtimestamp(ts, UTC)
                )
        return quotes

    def _events(self, listing: ListingRef, start: date, end: date) -> dict[str, Any]:
        symbol = listing.symbol_for(self.name)
        result = self._chart(
            symbol,
            period1=_epoch(start),
            period2=_epoch(end + timedelta(days=1)),
            events="div|split",
        )
        return {
            "events": result.get("events") or {},
            "tz": result.get("meta", {}).get("exchangeTimezoneName"),
            "currency": result.get("meta", {}).get("currency"),
        }

    def get_dividends(self, listing: ListingRef, start: date, end: date) -> list[DividendEvent]:
        data = self._events(listing, start, end)
        found = (data["events"].get("dividends") or {}).values()
        return sorted(
            (
                DividendEvent(
                    ex_date=_local_date(int(item["date"]), data["tz"]),
                    amount=Decimal(str(item["amount"])),
                    currency=data["currency"],
                )
                for item in found
            ),
            key=lambda d: d.ex_date,
        )

    def get_splits(self, listing: ListingRef, start: date, end: date) -> list[SplitEvent]:
        data = self._events(listing, start, end)
        found = (data["events"].get("splits") or {}).values()
        return sorted(
            (
                SplitEvent(
                    ex_date=_local_date(int(item["date"]), data["tz"]),
                    ratio=Decimal(str(item["numerator"])) / Decimal(str(item["denominator"])),
                )
                for item in found
            ),
            key=lambda s: s.ex_date,
        )

    def probe(self, symbol: str) -> SymbolMeta | None:
        meta = self._chart(symbol, range="5d").get("meta", {})
        currency = meta.get("currency")
        if not currency:
            return None
        return SymbolMeta(
            symbol=symbol,
            currency=str(currency).upper(),
            exchange_name=meta.get("fullExchangeName") or meta.get("exchangeName"),
            timezone=meta.get("exchangeTimezoneName"),
            instrument_type=meta.get("instrumentType"),
        )

    def search(self, query: str) -> list[SearchHit]:
        response = self._http.request(
            "GET",
            f"{SEARCH_BASE}/v1/finance/search",
            params={"q": query, "quotesCount": 15, "newsCount": 0},
        )
        check_status(self.name, response)
        try:
            quotes = response.json().get("quotes") or []
        except ValueError as exc:
            raise ProviderError("Yahoo sent a response that could not be read.") from exc
        return [
            SearchHit(
                symbol=q["symbol"],
                name=q.get("longname") or q.get("shortname"),
                exchange_code=q.get("exchange"),
                instrument_type=q.get("quoteType"),
            )
            for q in quotes
            if q.get("symbol")
        ]


def _at(values: Any, i: int) -> Any:
    return values[i] if values is not None and i < len(values) else None


def _volume(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


__all__ = ["YahooProvider", "NotSupported"]
