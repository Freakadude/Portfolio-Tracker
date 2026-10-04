"""Add an instrument by ISIN (FR-INS-01): list its tradable listings and confirm each one's
trading currency, so the owner can pick the pricing listing.

OpenFIGI supplies the listings (exchange code and ticker, not currency); a price provider's
metadata then confirms the currency. A currency no provider could confirm is only a guess based
on the exchange and is flagged as such.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from folio.marketdata import exchanges
from folio.marketdata.base import ProviderError, SymbolMeta
from folio.marketdata.fallback import ProviderChain
from folio.marketdata.isin import normalize_isin
from folio.marketdata.openfigi import FigiListing, FigiMapper

_ISSUERS = {
    "ISHARES": "iShares",
    "VANECK": "VanEck",
    "HANETF": "HANetf",
    "HSBC": "HSBC",
    "SPDR": "SPDR",
    "XTRACKERS": "Xtrackers",
    "AMUNDI": "Amundi",
    "INVESCO": "Invesco",
    "VANGUARD": "Vanguard",
    "WISDOMTREE": "WisdomTree",
    "UBS": "UBS",
}
_UPPER_TOKENS = {
    "ETF",
    "ETC",
    "ETN",
    "UCITS",
    "S&P",
    "MSCI",
    "USD",
    "EUR",
    "GBP",
    "NV",
    "ASML",
    "SA",
}
_PENCE = {"GBp", "GBX"}
_ORDER = {mic: i for i, mic in enumerate(exchanges.EXCHANGES)}


@dataclass(frozen=True)
class Candidate:
    mic: str
    exchange_name: str
    ticker: str
    currency: str
    currency_confirmed: bool
    confirmed_by: str | None
    figi: str
    provider_symbols: dict[str, str]
    usable: bool = True
    warning: str | None = None


@dataclass(frozen=True)
class Resolution:
    isin: str
    name: str
    asset_class: str
    issuer: str | None
    domicile: str
    candidates: list[Candidate] = field(default_factory=list)


def friendly_name(raw: str) -> str:
    """'ISHARES CORE S&P 500' -> 'iShares Core S&P 500' (editable by the owner anyway)."""
    words = []
    for word in raw.split():
        upper = word.upper()
        if upper in _ISSUERS:
            words.append(_ISSUERS[upper])
        elif upper in _UPPER_TOKENS or re.fullmatch(r"[A-Z]?\d+[A-Z]?", upper):
            words.append(upper)
        else:
            words.append(word.capitalize())
    return " ".join(words)


def guess_issuer(raw_name: str) -> str | None:
    first = raw_name.split()[0].upper() if raw_name.split() else ""
    return _ISSUERS.get(first)


def guess_asset_class(figi_type: str | None, provider_type: str | None, name: str) -> str:
    upper = name.upper()
    if provider_type and provider_type.upper() == "EQUITY":
        return "EQUITY"
    if figi_type and "COMMON STOCK" in figi_type.upper():
        return "EQUITY"
    if any(word in upper for word in ("PHYSICAL GOLD", "PHYSICAL SILVER", " ETC", "COMMODIT")):
        return "ETC"
    if "BOND" in upper and figi_type == "ETP":
        return "ETF"
    return "ETF" if figi_type in ("ETP", None) or provider_type == "ETF" else "OTHER"


def _candidate(listing: FigiListing, chain: ProviderChain) -> Candidate | None:
    mic = exchanges.BLOOMBERG_TO_MIC.get(listing.exch_code)
    if mic is None or not listing.ticker:
        return None
    exchange = exchanges.EXCHANGES[mic]
    symbols = exchanges.provider_symbols(mic, listing.ticker)
    meta: SymbolMeta | None = None
    confirmed_by: str | None = None
    try:
        probed = chain.probe_listing(symbols)
    except ProviderError:
        probed = None
    if probed is not None:
        meta, confirmed_by = probed.data, probed.source
    if meta is None:
        return Candidate(
            mic=mic,
            exchange_name=exchange.name,
            ticker=listing.ticker,
            currency=exchange.default_currency,
            currency_confirmed=False,
            confirmed_by=None,
            figi=listing.figi,
            provider_symbols=symbols,
            warning=(
                "No price provider could confirm the trading currency; "
                f"{exchange.default_currency} is a guess based on the exchange. "
                "Check it before choosing this listing."
            ),
        )
    if meta.currency in _PENCE:
        return Candidate(
            mic=mic,
            exchange_name=exchange.name,
            ticker=listing.ticker,
            currency="GBX",
            currency_confirmed=True,
            confirmed_by=confirmed_by,
            figi=listing.figi,
            provider_symbols=symbols,
            usable=False,
            warning="Quoted in pence, which Folio does not support yet. Pick another listing.",
        )
    return Candidate(
        mic=mic,
        exchange_name=exchange.name,
        ticker=listing.ticker,
        currency=meta.currency.upper(),
        currency_confirmed=True,
        confirmed_by=confirmed_by,
        figi=listing.figi,
        provider_symbols=symbols,
    )


def resolve_isin(raw_isin: str, figi: FigiMapper, chain: ProviderChain) -> Resolution:
    """Raises ValueError for a malformed ISIN and ProviderError if OpenFIGI cannot be reached."""
    isin = normalize_isin(raw_isin)
    listings = figi.map_isin(isin)
    seen: set[tuple[str, str]] = set()
    unique: list[FigiListing] = []
    for item in listings:
        mic = exchanges.BLOOMBERG_TO_MIC.get(item.exch_code)
        if mic is None or (mic, item.ticker) in seen:
            continue
        seen.add((mic, item.ticker))
        unique.append(item)
    unique.sort(key=lambda i: (_ORDER[exchanges.BLOOMBERG_TO_MIC[i.exch_code]], i.ticker))

    candidates = [c for c in (_candidate(item, chain) for item in unique) if c is not None]
    best = unique[0] if unique else (listings[0] if listings else None)
    raw_name = best.name if best else ""
    provider_type = None
    return Resolution(
        isin=isin,
        name=friendly_name(raw_name) if raw_name else "",
        asset_class=guess_asset_class(
            best.security_type if best else None, provider_type, raw_name
        ),
        issuer=guess_issuer(raw_name),
        domicile=isin[:2],
        candidates=candidates,
    )
