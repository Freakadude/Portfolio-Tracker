"""What a job needs to run: a database, a way to build providers, and a clock."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session, sessionmaker

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.marketdata.budget import CircuitBreaker, UsageTracker
from folio.marketdata.ecb import EcbRates
from folio.marketdata.eodhd import EodhdProvider
from folio.marketdata.fallback import ProviderChain
from folio.marketdata.fred import FredSeries
from folio.marketdata.http import HttpClient
from folio.marketdata.runtime import make_provider_factory, make_usage_tracker
from folio.news.fetch import Fetcher
from folio.notify.channels import Channel
from folio.notify.service import build_channels
from folio.security.secrets import SecretStore


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class JobContext:
    session_factory: sessionmaker[Session]
    chain_for: Callable[[Session], ProviderChain]
    ecb_for: Callable[[Session], EcbRates]
    now: Callable[[], datetime] = field(default=_utc_now)
    usage: UsageTracker | None = None  # lets the quote job keep budget for the nightly closes
    fred_for: Callable[[Session], FredSeries | None] = field(default=lambda db: None)
    channels_for: Callable[[Session], dict[str, Channel]] = field(default=lambda db: {})
    eodhd_for: Callable[[Session], EodhdProvider | None] = field(default=lambda db: None)
    issuer_for: Callable[[Session], HttpClient | None] = field(default=lambda db: None)
    # one fetcher for the whole worker, so its robots.txt cache and pacing persist
    fetcher_for: Callable[[], Fetcher | None] = field(default=lambda: None)

    def today(self) -> date:
        return self.now().date()


def build_context(settings: Settings) -> JobContext:
    """The production context: providers come from Settings > Providers and the encrypted keys."""
    settings.require_secret_key()
    factory = make_session_factory(make_engine(settings.db_url))
    usage = make_usage_tracker(factory)
    breakers: dict[str, CircuitBreaker] = {}  # shared, so a provider that is down stays paused

    def providers(db: Session):  # type: ignore[no-untyped-def]
        return make_provider_factory(db, settings, usage, breakers)

    def news_client(domain: str) -> HttpClient:
        return HttpClient(
            "news", usage=usage, breaker=breakers.setdefault(f"news:{domain}", CircuitBreaker())
        )

    fetcher = Fetcher(news_client, clock=_utc_now)

    return JobContext(
        session_factory=factory,
        chain_for=lambda db: providers(db).chain(),
        ecb_for=lambda db: providers(db).ecb(),
        usage=usage,
        fred_for=lambda db: providers(db).fred(),
        eodhd_for=lambda db: providers(db).eodhd(),
        issuer_for=lambda db: providers(db).issuer(),
        fetcher_for=lambda: fetcher,
        channels_for=lambda db: build_channels(
            db, SecretStore(db, settings.require_secret_key()).get
        ),
    )
