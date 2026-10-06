"""Provider fallback and registry (FR-MD-01, FR-MD-11)."""

from datetime import date
from decimal import Decimal

import httpx
import pytest

from folio.marketdata.base import (
    BudgetExhausted,
    ListingRef,
    NotSupported,
    ProviderError,
    ProviderUnavailable,
    SplitEvent,
    SymbolNotFound,
)
from folio.marketdata.fake import FakeProvider, make_bars
from folio.marketdata.fallback import AllProvidersFailed, ProviderChain
from folio.marketdata.registry import ProviderFactory
from folio.settings_schema import ProviderConfig, ProvidersSettings

LISTING = ListingRef(
    listing_id=1,
    exchange_mic="XETR",
    ticker="SXR8",
    currency="EUR",
    provider_symbols={"primary": "SXR8.XETRA", "backup": "SXR8.DE"},
)
START, END = date(2024, 1, 2), date(2024, 1, 5)
BARS = make_bars(START, ["100", "101", "102", "103"])


def test_the_fake_provider_drives_the_chain_without_network() -> None:
    fake = FakeProvider(name="primary", bars={1: BARS})
    result = ProviderChain([fake]).get_eod(LISTING, START, END)
    assert result.source == "primary" and len(result.data) == 4
    assert fake.calls == [("eod", 1)]


@pytest.mark.parametrize(
    "failure",
    [
        ProviderError("gateway timeout after 3 attempts"),
        BudgetExhausted("daily budget used up"),
        ProviderUnavailable("paused after repeated failures"),
        SymbolNotFound("unknown symbol"),
        NotSupported("not offered"),
    ],
)
def test_a_killed_primary_still_yields_closes_from_the_fallback(failure: Exception) -> None:
    primary = FakeProvider(name="primary", bars={1: BARS}, error=failure)
    backup = FakeProvider(name="backup", bars={1: BARS})
    result = ProviderChain([primary, backup]).get_eod(LISTING, START, END)
    assert result.source == "backup"  # each result says which provider produced it
    assert [b.close for b in result.data] == [Decimal(c) for c in ("100", "101", "102", "103")]


def test_the_primary_is_preferred_when_it_works() -> None:
    primary = FakeProvider(name="primary", bars={1: BARS})
    backup = FakeProvider(name="backup", bars={1: BARS})
    assert ProviderChain([primary, backup]).get_eod(LISTING, START, END).source == "primary"
    assert backup.calls == []


def test_an_empty_answer_falls_through_when_data_was_expected() -> None:
    # e.g. a free plan that only holds one year of history answers a 2015 range with nothing
    primary = FakeProvider(name="primary", bars={})
    backup = FakeProvider(name="backup", bars={1: BARS})
    chain = ProviderChain([primary, backup])
    assert chain.get_eod(LISTING, START, END, require_bars=True).source == "backup"
    # ...but an empty answer is fine when the range has no trading days (a weekend)
    assert chain.get_eod(LISTING, START, END).data == []


def test_when_every_provider_fails_the_reasons_are_listed() -> None:
    a = FakeProvider(name="primary", error=ProviderError("HTTP 503"))
    b = FakeProvider(name="backup", error=BudgetExhausted("budget gone"))
    with pytest.raises(AllProvidersFailed) as err:
        ProviderChain([a, b]).get_eod(LISTING, START, END)
    assert err.value.failures == {"primary": "HTTP 503", "backup": "budget gone"}
    assert "primary: HTTP 503; backup: budget gone" in str(err.value)


def test_with_no_provider_enabled_the_message_says_so() -> None:
    with pytest.raises(AllProvidersFailed, match="No provider is enabled"):
        ProviderChain([]).get_eod(LISTING, START, END)


def test_splits_and_probe_use_the_same_fallback() -> None:
    split = SplitEvent(date(2024, 2, 1), Decimal(4))
    primary = FakeProvider(name="primary", error=ProviderError("down"))
    backup = FakeProvider(name="backup", splits={1: [split]}, currencies={"SXR8.DE": "EUR"})
    chain = ProviderChain([primary, backup])
    assert chain.get_splits(LISTING, START, date(2024, 3, 1)).data == [split]
    probed = chain.probe("SXR8.DE")
    assert probed is not None and probed.data.currency == "EUR" and probed.source == "backup"
    assert chain.probe("UNKNOWN") is None


def _factory(config: ProvidersSettings, secrets: dict[str, str]) -> ProviderFactory:
    return ProviderFactory(config, secrets.get)


def test_registry_defaults_use_yahoo_only_until_keys_exist() -> None:
    names = [p.name for p in _factory(ProvidersSettings(), {}).price_providers()]
    assert names == ["yahoo"]  # owner decision: Yahoo on by default; keyed providers need a key


def test_registry_orders_providers_by_priority_once_keyed() -> None:
    secrets = {"providers.eodhd_api_key": "k1", "providers.twelvedata_api_key": "k2"}
    names = [p.name for p in _factory(ProvidersSettings(), secrets).price_providers()]
    assert names == ["eodhd", "yahoo", "twelvedata"]


def test_registry_respects_priority_and_enabled_settings() -> None:
    config = ProvidersSettings(
        providers={
            "yahoo": ProviderConfig(enabled=True, priority=1),
            "eodhd": ProviderConfig(enabled=True, priority=2),
            "twelvedata": ProviderConfig(enabled=False, priority=3),
        }
    )
    secrets = {"providers.eodhd_api_key": "k1", "providers.twelvedata_api_key": "k2"}
    names = [p.name for p in _factory(config, secrets).price_providers()]
    assert names == ["yahoo", "eodhd"]  # twelvedata is disabled even though it has a key
    yahoo_off = ProvidersSettings(providers={"yahoo": ProviderConfig(enabled=False)})
    assert _factory(yahoo_off, {}).price_providers() == []


def _switched_off(name: str) -> tuple[ProviderFactory, list[str]]:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={})

    config = ProvidersSettings(providers={name: ProviderConfig(enabled=False)})
    secrets = {"providers.fred_api_key": "k", "providers.eodhd_api_key": "k"}
    return ProviderFactory(config, secrets.get, transport=httpx.MockTransport(handler)), calls


def test_a_provider_switched_off_in_settings_is_never_called() -> None:
    """Settings, Providers has an on/off switch per provider: a switched-off one makes no request
    and says why, whichever part of Folio asks."""
    factory, calls = _switched_off("ecb")
    with pytest.raises(ProviderError, match="ecb is switched off in Settings"):
        factory.ecb().deposit_rate(date(2024, 1, 2))
    factory, calls_figi = _switched_off("openfigi")
    with pytest.raises(ProviderError, match="openfigi is switched off in Settings"):
        factory.figi().map_isin("IE00B5BMR087")
    assert calls == [] and calls_figi == []


@pytest.mark.parametrize("name", ["fred", "eodhd"])
def test_keyed_providers_switched_off_are_left_out(name: str) -> None:
    factory, _ = _switched_off(name)
    assert (factory.fred() if name == "fred" else factory.eodhd()) is None
