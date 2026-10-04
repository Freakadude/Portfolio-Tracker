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
from folio.marketdata.fallback import ProviderChain
from folio.marketdata.registry import ProviderFactory
from folio.security.secrets import SecretStore
from folio.settings_store import load_section


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
    secret_key = settings.require_secret_key()
    factory = make_session_factory(make_engine(settings.db_url))
    breakers: dict[str, CircuitBreaker] = {}  # shared, so a provider that is down stays paused

    def current_providers() -> object:
        with factory() as db:
            return load_section(db, "providers")

    def limit_for(provider: str) -> int:
        config = current_providers().providers.get(provider)  # type: ignore[attr-defined]
        return 0 if config is None else int(config.daily_call_budget)

    usage = UsageTracker(factory, limit_for)

    def provider_factory(db: Session) -> ProviderFactory:
        config = load_section(db, "providers")
        store = SecretStore(db, secret_key)
        return ProviderFactory(config, store.get, usage, breakers)  # type: ignore[arg-type]

    return JobContext(
        session_factory=factory,
        chain_for=lambda db: provider_factory(db).chain(),
        ecb_for=lambda db: provider_factory(db).ecb(),
    )
