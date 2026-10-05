"""Builds the configured providers from Settings > Providers (priorities, enabled flags, daily
budgets) and the encrypted API keys. Providers that need a key and have none are left out."""

from __future__ import annotations

from collections.abc import Callable

import httpx

from folio.marketdata.base import PriceProvider
from folio.marketdata.budget import CircuitBreaker, UsageTracker
from folio.marketdata.ecb import EcbRates
from folio.marketdata.eodhd import EodhdProvider
from folio.marketdata.fallback import ProviderChain
from folio.marketdata.fred import FredSeries
from folio.marketdata.http import HttpClient
from folio.marketdata.openfigi import FigiMapper
from folio.marketdata.twelvedata import TwelveDataProvider
from folio.marketdata.yahoo import YahooProvider
from folio.settings_schema import ProviderConfig, ProvidersSettings

NEEDS_KEY = {"eodhd", "twelvedata"}


class ProviderFactory:
    def __init__(
        self,
        config: ProvidersSettings,
        get_secret: Callable[[str], str | None],
        usage: UsageTracker | None = None,
        breakers: dict[str, CircuitBreaker] | None = None,
        transport: httpx.BaseTransport | None = None,
        **http_options: object,
    ) -> None:
        self._config = config
        self._get_secret = get_secret
        self._usage = usage
        # Shared across factories in one process so a provider that is down stays paused.
        self._breakers = breakers if breakers is not None else {}
        self._transport = transport
        self._http_options = http_options

    def _key(self, provider: str) -> str | None:
        return self._get_secret(f"providers.{provider}_api_key")

    def _http(self, provider: str) -> HttpClient:
        breaker = self._breakers.setdefault(provider, CircuitBreaker())
        return HttpClient(
            provider,
            usage=self._usage,
            breaker=breaker,
            transport=self._transport,
            **self._http_options,  # type: ignore[arg-type]
        )

    def _cfg(self, provider: str) -> ProviderConfig:
        return self._config.providers.get(provider, ProviderConfig())

    def price_providers(self) -> list[PriceProvider]:
        """Enabled price providers, lowest priority number first."""
        built: list[tuple[int, PriceProvider]] = []
        for name in ("eodhd", "twelvedata", "yahoo"):
            cfg = self._cfg(name)
            if not cfg.enabled:
                continue
            key = self._key(name)
            if name in NEEDS_KEY and not key:
                continue
            provider: PriceProvider
            if name == "eodhd":
                provider = EodhdProvider(self._http(name), key or "")
            elif name == "twelvedata":
                provider = TwelveDataProvider(self._http(name), key or "")
            else:
                provider = YahooProvider(self._http(name))
            built.append((cfg.priority, provider))
        return [p for _, p in sorted(built, key=lambda item: item[0])]

    def chain(self) -> ProviderChain:
        return ProviderChain(self.price_providers())

    def figi(self) -> FigiMapper:
        return FigiMapper(self._http("openfigi"), self._key("openfigi"))

    def ecb(self) -> EcbRates:
        return EcbRates(self._http("ecb"))

    def fred(self) -> FredSeries | None:
        """FRED needs a free API key; without one (or switched off) there is no FRED."""
        key = self._key("fred")
        if not key or not self._cfg("fred").enabled:
            return None
        return FredSeries(self._http("fred"), key)
