"""Linking a story to what the owner holds (FR-NW-05).

Deterministic matching comes first: an ISIN or ticker in the text, a ticker EODHD tagged the
article with, or a name or alias of a holding or watched instrument. Then the ETFs: a story about
a company inside an ETF links to the ETF with the company's weight there ("look-through"). Each
link says how it was found (`matched_by`), so a "not relevant" mark can lower the right alias
(FR-NW-08).

Relevance combines how the link was found, how much of the portfolio it touches, how much the
source is trusted and how fresh the story is.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Literal

ALIAS_FLOOR = Decimal("0.3")  # an alias with less weight than this no longer matches
MIN_KEY_LENGTH = 4  # shorter names ("on", "f") would match half the news
SATURATION = Decimal("0.10")  # a link touching 10 % of the portfolio or more counts in full
HALF_LIFE_HOURS = Decimal(24)

LinkKind = Literal["direct", "look_through", "macro", "theme"]
TYPE_FACTOR: dict[str, Decimal] = {
    "direct": Decimal(1),
    "look_through": Decimal("0.8"),
    "macro": Decimal("0.5"),
    "theme": Decimal("0.4"),
}

_ISIN = re.compile(r"\b[A-Z]{2}[A-Z0-9]{9}[0-9]\b")
_UPPER_WORD = re.compile(r"\b[A-Z][A-Z0-9]{2,9}\b")
_WORD = re.compile(r"[a-z0-9]+")


def tokens_of(text: str) -> list[str]:
    return _WORD.findall(text.lower().replace(".", ""))


@dataclass(frozen=True)
class Subject:
    """A holding or watched instrument that news can be about."""

    instrument_id: int
    name: str
    isin: str | None
    ticker: str | None
    eodhd_symbol: str | None
    exposure: Decimal  # its share of the portfolio (0 for a watchlist item)


@dataclass(frozen=True)
class AliasRule:
    instrument_id: int
    phrase: str  # normalised: lower case words separated by single spaces
    weight: Decimal


@dataclass(frozen=True)
class ConstituentRule:
    """A company inside an ETF the owner holds."""

    etf_id: int
    phrase: str
    isin: str | None
    name: str
    weight_pct: Decimal  # its weight inside the ETF


@dataclass(frozen=True)
class Hit:
    instrument_id: int
    kind: Literal["direct", "look_through"]
    matched_by: str  # isin:X, eodhd:X, ticker:X, alias:phrase or constituent:phrase
    weight_pct: Decimal | None = None  # inside the ETF, for look-through
    alias_weight: Decimal = Decimal(1)


_PRIORITY = {"isin": 0, "eodhd": 1, "ticker": 2, "alias": 3, "constituent": 4}


class Matcher:
    def __init__(
        self,
        subjects: Sequence[Subject],
        aliases: Iterable[AliasRule] = (),
        constituents: Iterable[ConstituentRule] = (),
    ) -> None:
        self._subjects = list(subjects)
        self._aliases = [a for a in aliases if a.weight >= ALIAS_FLOOR and a.phrase]
        self._constituents = [c for c in constituents if len(c.phrase) >= MIN_KEY_LENGTH]

    def match(self, text: str, symbols: Sequence[str] = ()) -> list[Hit]:
        padded = " " + " ".join(tokens_of(text)) + " "
        isins = set(_ISIN.findall(text.upper()))
        words = set(_UPPER_WORD.findall(text))
        tagged = {s.upper() for s in symbols}
        found: dict[tuple[int, str], Hit] = {}

        def add(hit: Hit) -> None:
            key = (hit.instrument_id, hit.kind)
            old = found.get(key)
            if old is None or _better(hit, old):
                found[key] = hit

        for s in self._subjects:
            if s.isin and s.isin in isins:
                add(Hit(s.instrument_id, "direct", f"isin:{s.isin}"))
            if s.eodhd_symbol and s.eodhd_symbol.upper() in tagged:
                add(Hit(s.instrument_id, "direct", f"eodhd:{s.eodhd_symbol}"))
            if s.ticker and len(s.ticker) >= 3 and s.ticker.upper() in words:
                add(Hit(s.instrument_id, "direct", f"ticker:{s.ticker}"))
        for a in self._aliases:
            if f" {a.phrase} " in padded:
                add(Hit(a.instrument_id, "direct", f"alias:{a.phrase}", alias_weight=a.weight))
        for c in self._constituents:
            if (c.isin and c.isin in isins) or f" {c.phrase} " in padded:
                add(
                    Hit(
                        c.etf_id,
                        "look_through",
                        f"constituent:{c.phrase}",
                        weight_pct=c.weight_pct,
                    )
                )
        return sorted(found.values(), key=lambda h: (h.instrument_id, h.kind))


def _better(new: Hit, old: Hit) -> bool:
    """A look-through hit keeps the larger weight; a direct hit the surer way of finding it."""
    if new.kind == "look_through":
        return (new.weight_pct or Decimal(0)) > (old.weight_pct or Decimal(0))
    return _PRIORITY[new.matched_by.split(":")[0]] < _PRIORITY[old.matched_by.split(":")[0]]


def relevance(
    kind: str,
    exposure: Decimal,
    trust: Decimal,
    age: timedelta,
    alias_weight: Decimal = Decimal(1),
) -> Decimal:
    """0 to 1: the way the link was found, times how much of the portfolio it touches (a
    watchlist item still counts a little), times source trust, times a freshness that halves
    every 24 hours."""
    size = Decimal("0.2") + Decimal("0.8") * min(Decimal(1), exposure / SATURATION)
    hours = Decimal(max(age.total_seconds(), 0)) / Decimal(3600)
    freshness = Decimal("0.5") ** (hours / HALF_LIFE_HOURS)
    value = TYPE_FACTOR[kind] * size * trust * freshness * alias_weight
    return value.quantize(Decimal("0.0001"))


# --- macro stories (FR-NW-10) -------------------------------------------------------------------

MACRO_TERMS = (
    "interest rate", "key rate", "policy rate", "federal funds", "fomc", "monetary policy",
    "rate decision", "target range", "deposit facility", "main refinancing", "inflation",
    "exchange rate", "dollar", "treasury", "yield", "balance sheet", "quantitative",
    "governing council", "press conference", "rates",
)  # fmt: skip


def is_macro_story(text: str) -> bool:
    """A central bank's release that is about rates, money or the currency, as opposed to an
    approval of a bank merger or an enforcement action."""
    lowered = text.lower()
    return any(term in lowered for term in MACRO_TERMS)
