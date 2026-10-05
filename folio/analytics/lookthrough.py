"""Look-through allocation (FR-PF-05).

Each position is opened up: an ETF with a holdings snapshot becomes its constituents, each worth
the ETF's value times the constituent's weight; anything else stays itself. The pieces are then
added up by company, sector, country or currency, so a company held directly and inside two ETFs
shows as one exposure, with a breakdown of where it comes from.

Whatever the file does not cover (cash, derivatives, a top-N file) is kept as "Other holdings of
<ETF>", so the exposures always add up to the value of the positions that were opened. A fund
without holdings stays itself and is marked as a fund, never counted as a company.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Literal

from folio.lookthrough.parse import Constituent

ZERO = Decimal(0)
HUNDRED = Decimal(100)
EPSILON = Decimal("0.000001")  # euros; a smaller remainder is rounding, not holdings

DIMENSIONS = ("company", "sector", "country", "currency")
UNCLASSIFIED = "Unclassified"
OTHER = "Other holdings"

Kind = Literal["direct", "look_through", "fund", "other"]

_COUNTRIES = {
    "US": "United States", "GB": "United Kingdom", "NL": "Netherlands", "DE": "Germany",
    "FR": "France", "IE": "Ireland", "CH": "Switzerland", "ES": "Spain", "IT": "Italy",
    "BE": "Belgium", "LU": "Luxembourg", "SE": "Sweden", "DK": "Denmark", "NO": "Norway",
    "FI": "Finland", "AT": "Austria", "PT": "Portugal", "JP": "Japan", "CN": "China",
    "HK": "Hong Kong", "TW": "Taiwan", "KR": "South Korea", "IN": "India", "AU": "Australia",
    "CA": "Canada", "BR": "Brazil", "MX": "Mexico", "ZA": "South Africa", "SG": "Singapore",
    "SA": "Saudi Arabia", "IL": "Israel", "PL": "Poland", "TR": "Turkey", "ID": "Indonesia",
    "TH": "Thailand", "MY": "Malaysia", "NZ": "New Zealand",
}  # fmt: skip
_COUNTRY_ALIASES = {
    "usa": "United States",
    "u.s.": "United States",
    "united states of america": "United States",
    "uk": "United Kingdom",
    "great britain": "United Kingdom",
    "korea": "South Korea",
    "republic of korea": "South Korea",
    "the netherlands": "Netherlands",
    "holland": "Netherlands",
}
_SECTORS = {
    "technology": "Information Technology",
    "information technology": "Information Technology",
    "financial services": "Financials",
    "financial": "Financials",
    "healthcare": "Health Care",
    "health care": "Health Care",
    "consumer cyclical": "Consumer Discretionary",
    "consumer discretionary": "Consumer Discretionary",
    "consumer defensive": "Consumer Staples",
    "consumer staples": "Consumer Staples",
    "basic materials": "Materials",
    "materials": "Materials",
    "communication services": "Communication",
    "communication": "Communication",
    "telecommunications": "Communication",
    "real estate": "Real Estate",
    "utilities": "Utilities",
    "energy": "Energy",
    "industrials": "Industrials",
}
_SUFFIXES = {
    "inc", "corp", "corporation", "co", "ltd", "limited", "plc", "nv", "sa", "se", "ag", "ab",
    "asa", "spa", "oyj", "the", "holding", "holdings", "group", "class", "ordinary", "shares",
}  # fmt: skip
_NOT_ALNUM = re.compile(r"[^a-z0-9]+")


def company_key(name: str, isin: str | None) -> str:
    """How constituents are told apart across wrappers: by ISIN when a file has one, else by the
    name without legal suffixes and punctuation ("ASML Holding N.V." and "ASML HOLDING NV")."""
    if isin:
        return isin.upper()
    words = [
        w for w in _NOT_ALNUM.sub(" ", name.lower().replace(".", "")).split() if w not in _SUFFIXES
    ]
    return " ".join(words) or name.strip().lower()


def country_name(text: str | None) -> str | None:
    """A country as one English name, whether the source gave a code, 'USA' or the full name."""
    if not text or not text.strip() or text.strip() == "-":
        return None
    raw = text.strip()
    if len(raw) == 2 and raw.upper() in _COUNTRIES:
        return _COUNTRIES[raw.upper()]
    return _COUNTRY_ALIASES.get(raw.lower(), raw)


def sector_name(text: str | None) -> str | None:
    """Sector names differ by data source ("Technology" and "Information Technology"); the
    common ones are mapped to one name so they add up."""
    if not text or not text.strip() or text.strip() == "-":
        return None
    raw = text.strip()
    return _SECTORS.get(raw.lower(), raw)


@dataclass(frozen=True)
class Wrapper:
    """A position the owner holds, which may be an ETF with holdings or a plain holding."""

    instrument_id: int
    name: str
    isin: str | None
    value_eur: Decimal
    sector: str | None = None
    country: str | None = None
    currency: str | None = None
    is_fund: bool = False  # an ETF or fund: without holdings it is not a single company


@dataclass(frozen=True)
class Holdings:
    """What one ETF holds, from its newest snapshot."""

    covered_pct: Decimal
    constituents: Sequence[Constituent]


@dataclass(frozen=True)
class Part:
    """Where part of an exposure comes from."""

    source: str  # the position it sits in
    instrument_id: int
    kind: Kind
    value_eur: Decimal
    weight_pct: Decimal | None  # the constituent's weight inside the ETF


@dataclass(frozen=True)
class Exposure:
    key: str
    label: str
    value_eur: Decimal
    weight: Decimal  # fraction of everything that was opened up
    parts: tuple[Part, ...]
    other: bool  # not a single company: an ETF's unnamed rest, or a fund shown as itself


@dataclass(frozen=True)
class Atom:
    company: str
    name: str
    isin: str | None
    sector: str | None
    country: str | None
    currency: str | None
    value_eur: Decimal
    part: Part


def expand(wrappers: Sequence[Wrapper], holdings: Mapping[int, Holdings]) -> list[Atom]:
    """Open every position that has holdings into constituents; the rest stay as they are."""
    atoms: list[Atom] = []
    for w in wrappers:
        found = holdings.get(w.instrument_id)
        if found is None or not found.constituents:
            atoms.append(
                Atom(
                    company=company_key(w.name, w.isin),
                    name=w.name,
                    isin=w.isin,
                    sector=sector_name(w.sector),
                    country=country_name(w.country),
                    currency=w.currency.upper() if w.currency else None,
                    value_eur=w.value_eur,
                    part=Part(
                        w.name,
                        w.instrument_id,
                        "fund" if w.is_fund else "direct",
                        w.value_eur,
                        None,
                    ),
                )
            )
            continue
        with localcontext() as ctx:
            ctx.prec = 40
            scale = HUNDRED / found.covered_pct if found.covered_pct > HUNDRED else Decimal(1)
            opened: list[Atom] = []
            for c in found.constituents:
                value = w.value_eur * c.weight_pct / HUNDRED * scale
                opened.append(
                    Atom(
                        company=company_key(c.name, c.isin),
                        name=c.name,
                        isin=c.isin,
                        sector=sector_name(c.sector),
                        country=country_name(c.country),
                        currency=c.currency.upper() if c.currency else None,
                        value_eur=value,
                        part=Part(w.name, w.instrument_id, "look_through", value, c.weight_pct),
                    )
                )
            rest = w.value_eur - sum((a.value_eur for a in opened), ZERO)
        atoms.extend(opened)
        if rest > EPSILON:
            atoms.append(
                Atom(
                    company=f"other:{w.instrument_id}",
                    name=f"{OTHER} of {w.name}",
                    isin=None,
                    sector=None,
                    country=None,
                    currency=None,
                    value_eur=rest,
                    part=Part(w.name, w.instrument_id, "other", rest, None),
                )
            )
    return atoms


def _dimension_key(atom: Atom, dimension: str) -> tuple[str, str]:
    """(grouping key, label) of an atom in a dimension."""
    if dimension == "company":
        return atom.company, atom.name
    value = {"sector": atom.sector, "country": atom.country, "currency": atom.currency}[dimension]
    if value is None:
        return UNCLASSIFIED.lower(), UNCLASSIFIED
    return value.lower(), value


def aggregate(atoms: Sequence[Atom], dimension: str) -> list[Exposure]:
    """Add the atoms up by company, sector, country or currency, largest first."""
    if dimension not in DIMENSIONS:
        raise ValueError(f"Unknown dimension {dimension!r}; use one of {', '.join(DIMENSIONS)}.")
    groups: dict[str, list[Atom]] = {}
    labels: dict[str, str] = {}
    for atom in atoms:
        key, label = _dimension_key(atom, dimension)
        groups.setdefault(key, []).append(atom)
        labels.setdefault(key, label)
    total = sum((a.value_eur for a in atoms), ZERO)
    out: list[Exposure] = []
    for key, members in groups.items():
        value = sum((a.value_eur for a in members), ZERO)
        # the name a person would recognise: the one the owner's own holding carries, else
        # the name of the largest piece
        direct = [a for a in members if a.part.kind == "direct"]
        label = (direct or sorted(members, key=lambda a: -a.value_eur))[0].name
        if dimension != "company":
            label = labels[key]
        parts: dict[tuple[int, str], Part] = {}
        for a in members:
            k = (a.part.instrument_id, a.part.kind)
            existing = parts.get(k)
            if existing is None:
                parts[k] = a.part
            else:  # several constituents of one ETF in one sector or country
                parts[k] = Part(
                    existing.source,
                    existing.instrument_id,
                    existing.kind,
                    existing.value_eur + a.part.value_eur,
                    existing.weight_pct
                    if dimension == "company" or existing.weight_pct is None
                    else (existing.weight_pct + (a.part.weight_pct or ZERO)),
                )
        with localcontext() as ctx:
            ctx.prec = 40
            weight = ZERO if total == 0 else value / total
        out.append(
            Exposure(
                key=key,
                label=label,
                value_eur=value,
                weight=weight,
                parts=tuple(sorted(parts.values(), key=lambda p: -p.value_eur)),
                other=dimension == "company"
                and all(a.part.kind in ("other", "fund") for a in members),
            )
        )
    out.sort(key=lambda e: (-e.value_eur, e.key))
    return out


def concentration(exposures: Sequence[Exposure]) -> list[Exposure]:
    """The exposures a concentration limit applies to: real companies (or countries), never an
    ETF's unopened remainder, a fund whose holdings are not loaded, or the unclassified pile."""
    return [e for e in exposures if not e.other and e.key != UNCLASSIFIED.lower()]
