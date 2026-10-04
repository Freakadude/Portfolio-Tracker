"""Wiring shared by the web process and the worker: usage tracking against the current
Settings > Providers budgets, and a provider factory built from the stored settings and keys."""

from __future__ import annotations

import httpx
from sqlalchemy.orm import Session, sessionmaker

from folio.config import Settings
from folio.marketdata.budget import CircuitBreaker, UsageTracker
from folio.marketdata.registry import ProviderFactory
from folio.security.secrets import SecretStore
from folio.settings_store import load_section


def make_usage_tracker(session_factory: sessionmaker[Session]) -> UsageTracker:
    """Reads the daily budget from the settings on every charge, so a change in Settings
    takes effect immediately without restarting anything."""

    def limit_for(provider: str) -> int:
        with session_factory() as db:
            section = load_section(db, "providers")
        config = section.providers.get(provider)  # type: ignore[attr-defined]
        return 0 if config is None else int(config.daily_call_budget)

    return UsageTracker(session_factory, limit_for)


def make_provider_factory(
    db: Session,
    settings: Settings,
    usage: UsageTracker,
    breakers: dict[str, CircuitBreaker],
    transport: httpx.BaseTransport | None = None,
    **http_options: object,
) -> ProviderFactory:
    config = load_section(db, "providers")
    store = SecretStore(db, settings.require_secret_key())
    return ProviderFactory(
        config,  # type: ignore[arg-type]
        store.get,
        usage,
        breakers,
        transport,
        **http_options,
    )
