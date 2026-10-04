"""What a job needs to run: a database, a way to build providers, and a clock."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session, sessionmaker

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.marketdata.budget import CircuitBreaker
from folio.marketdata.ecb import EcbRates
from folio.marketdata.fallback import ProviderChain
from folio.marketdata.runtime import make_provider_factory, make_usage_tracker


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class JobContext:
    session_factory: sessionmaker[Session]
    chain_for: Callable[[Session], ProviderChain]
    ecb_for: Callable[[Session], EcbRates]
    now: Callable[[], datetime] = field(default=_utc_now)

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

    return JobContext(
        session_factory=factory,
        chain_for=lambda db: providers(db).chain(),
        ecb_for=lambda db: providers(db).ecb(),
    )
