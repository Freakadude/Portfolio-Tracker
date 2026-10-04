"""Shared helpers for provider tests: recorded fixtures and a scripted HTTP transport."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
from tenacity import wait_none

from folio.marketdata.http import HttpClient

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "providers"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class Scripted:
    """An httpx transport that answers from a handler and remembers every request."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._handler = handler
        self.transport = httpx.MockTransport(self._answer)

    def _answer(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)


def respond(name: str, status: int = 200, content_type: str = "application/json") -> httpx.Response:
    return httpx.Response(
        status, content=fixture_bytes(name), headers={"content-type": content_type}
    )


def client(provider: str, scripted: Scripted, **kwargs: object) -> HttpClient:
    """No real waiting between retries in tests."""
    kwargs.setdefault("wait", wait_none())
    return HttpClient(provider, transport=scripted.transport, **kwargs)  # type: ignore[arg-type]


# --- database-backed helpers -------------------------------------------------------------------

from datetime import UTC, date, datetime  # noqa: E402
from decimal import Decimal  # noqa: E402

from sqlalchemy.orm import Session  # noqa: E402

from folio.config import Settings  # noqa: E402
from folio.db.engine import make_engine, make_session_factory  # noqa: E402
from folio.db.models_ledger import Instrument, Listing  # noqa: E402
from folio.jobs.context import JobContext  # noqa: E402
from folio.marketdata import exchanges  # noqa: E402
from folio.marketdata.base import Bar, PriceProvider  # noqa: E402
from folio.marketdata.ecb import EcbRates  # noqa: E402
from folio.marketdata.fallback import ProviderChain  # noqa: E402


def make_listing(
    db: Session,
    ticker: str = "SXR8",
    mic: str = "XETR",
    currency: str = "EUR",
    isin: str | None = "IE00B5BMR087",
    manual: bool = False,
    status: str = "active",
    symbols: dict[str, str] | None = None,
) -> tuple[Instrument, Listing]:
    instrument = Instrument(
        isin=isin, name=f"{ticker} fund", asset_class="ETF", manual=manual, status=status
    )
    db.add(instrument)
    db.flush()
    listing = Listing(
        instrument_id=instrument.id,
        exchange_mic=mic,
        ticker=ticker,
        currency=currency,
        provider_symbols=symbols
        if symbols is not None
        else {"fake": ticker, "primary": ticker, "backup": ticker},
        pricing_primary=True,
    )
    db.add(listing)
    db.flush()
    return instrument, listing


def bars_for(mic: str, start: date, end: date, first_close: int = 100) -> list[Bar]:
    """One bar per real trading day, closes rising by one."""
    return [
        Bar(date=d, close=Decimal(first_close + i))
        for i, d in enumerate(exchanges.trading_days(mic, start, end))
    ]


def make_ctx(
    settings: Settings,
    providers: list[PriceProvider],
    ecb: Scripted | None = None,
    now: datetime | None = None,
) -> JobContext:
    fixed = now or datetime(2024, 1, 15, 12, 0, tzinfo=UTC)
    ecb_scripted = ecb or Scripted(lambda r: httpx.Response(404, json={}))
    return JobContext(
        session_factory=make_session_factory(make_engine(settings.db_url)),
        chain_for=lambda db: ProviderChain(providers),
        ecb_for=lambda db: EcbRates(client("ecb", ecb_scripted)),
        now=lambda: fixed,
    )
