"""Adding the instruments an import needs (FR-TX-07: "map instruments by ISIN").

A first import from a broker names instruments Folio does not know yet. Rather than sending
the owner to add each one by hand, the review step can add them all: each ISIN is looked up,
and the listing chosen is the one on the exchange the export names (Degiro's "Reference
exchange", e.g. XET or EAM), else one in the currency the trades were in, else the first one
Folio can price. An ISIN that cannot be looked up, or has no listing Folio can price, can be
added as a hand-priced instrument instead, with the product name and currency from the file.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session

from folio.imports.mapping import ImportMapping
from folio.imports.parse import ParsedFile
from folio.instruments import InstrumentError, ListingChoice, NewInstrument, create_instrument
from folio.jobs.requests import enqueue
from folio.marketdata.base import ProviderError
from folio.marketdata.fallback import ProviderChain
from folio.marketdata.openfigi import FigiMapper
from folio.marketdata.resolve import Candidate, Resolution, resolve_isin

# Degiro's own exchange codes, as in its "Reference exchange" column, to market identifier codes
DEGIRO_EXCHANGES = {
    "XET": "XETR",
    "EAM": "XAMS",
    "EPA": "XPAR",
    "MIL": "XMIL",
    "LSE": "XLON",
    "SWX": "XSWX",
    "NDQ": "XNAS",
    "NSY": "XNYS",
}
_NAME_HEADERS = ("product", "product name", "name", "naam", "instrument")
_EXCHANGE_HEADERS = ("reference exchange", "referentie beurs", "beurs", "exchange")


@dataclass(frozen=True)
class Missing:
    isin: str
    name: str  # from the file; may be empty
    exchange: str | None  # a market identifier code, when the file names one Folio knows
    currency: str | None  # the currency the trades were in
    rows: int


@dataclass(frozen=True)
class Added:
    isin: str
    name: str
    status: str  # added | manual | failed
    detail: str  # the listing chosen, or why nothing was added


def _column(headers: Sequence[str], names: Sequence[str]) -> int | None:
    lowered = [h.strip().lower() for h in headers]
    for name in names:
        if name in lowered:
            return lowered.index(name)
    return None


def _cell(cells: Sequence[str], col: int | None) -> str:
    return cells[col].strip() if col is not None and col < len(cells) else ""


def missing_instruments(
    parsed: ParsedFile, mapping: ImportMapping, unknown: Sequence[str]
) -> list[Missing]:
    """What the file says about each unknown ISIN: its name, exchange and trade currency."""
    wanted = {isin.upper() for isin in unknown}
    name_col = _column(parsed.headers, _NAME_HEADERS)
    exchange_col = _column(parsed.headers, _EXCHANGE_HEADERS)
    seen: dict[str, dict[str, object]] = {}
    for cells in parsed.rows:
        isin = _cell(cells, mapping.isin_col).upper()
        if isin not in wanted:
            continue
        info = seen.setdefault(isin, {"name": "", "exchange": None, "currency": None, "rows": 0})
        info["rows"] = int(str(info["rows"])) + 1
        if not info["name"]:
            info["name"] = _cell(cells, name_col)
        if info["exchange"] is None:
            code = _cell(cells, exchange_col).upper()
            info["exchange"] = DEGIRO_EXCHANGES.get(code) or (code if len(code) == 4 else None)
        if info["currency"] is None:
            currency = _cell(cells, mapping.currency_col).upper() or mapping.default_currency
            info["currency"] = currency or None
    return [
        Missing(
            isin=isin,
            name=str(info["name"]),
            exchange=None if info["exchange"] is None else str(info["exchange"]),
            currency=None if info["currency"] is None else str(info["currency"]),
            rows=int(str(info["rows"])),
        )
        for isin, info in ((i, seen[i]) for i in unknown if i in seen)
    ]


def pick_listing(candidates: Sequence[Candidate], missing: Missing) -> Candidate | None:
    """The exchange the export names first, then the trade currency, then the first usable."""
    usable = [c for c in candidates if c.usable]
    on_exchange = [c for c in usable if c.mic == missing.exchange]
    in_currency = [c for c in usable if c.currency == missing.currency]
    for group in (
        [c for c in on_exchange if c.currency == missing.currency],
        on_exchange,
        [c for c in in_currency if c.currency_confirmed],
        in_currency,
        usable,
    ):
        if group:
            return group[0]
    return None


def _name(missing: Missing, resolution: Resolution | None) -> str:
    if resolution is not None and resolution.name:
        return resolution.name
    return missing.name or missing.isin


def add_missing(
    db: Session,
    items: Sequence[Missing],
    figi: FigiMapper,
    chain: ProviderChain,
    *,
    by_hand: bool = False,
) -> list[Added]:
    """Add each instrument (looked up, or by hand), and queue the price history for the ones
    with a listing. One that fails does not stop the others.

    Every lookup happens before anything is written: a provider call is charged to the budget
    through another database connection, which must not find this one holding the write lock."""
    planned: list[tuple[Missing, NewInstrument, str]] = []
    out: list[Added] = []
    for missing in items:
        if by_hand:
            data = NewInstrument(
                name=missing.name or missing.isin,
                asset_class="OTHER",
                isin=missing.isin,
                manual=True,
                currency=missing.currency or "EUR",
            )
            planned.append((missing, data, f"hand-priced in {missing.currency or 'EUR'}"))
            continue
        try:
            resolution = resolve_isin(missing.isin, figi, chain)
        except (ValueError, ProviderError) as exc:
            out.append(Added(missing.isin, missing.name, "failed", f"Lookup failed: {exc}"))
            continue
        choice = pick_listing(resolution.candidates, missing)
        if choice is None:
            out.append(
                Added(
                    missing.isin,
                    _name(missing, resolution),
                    "failed",
                    "No listing Folio can price was found; add it by hand.",
                )  # fmt: skip
            )
            continue
        data = NewInstrument(
            name=_name(missing, resolution),
            asset_class=resolution.asset_class,
            issuer=resolution.issuer,
            domicile=resolution.domicile,
            isin=missing.isin,
            listing=ListingChoice(mic=choice.mic, ticker=choice.ticker, currency=choice.currency),
        )
        planned.append(
            (missing, data, f"{choice.exchange_name} · {choice.ticker} · {choice.currency}")
        )

    for missing, data, detail in planned:
        try:
            instrument, listing, _ = create_instrument(db, data)
        except (InstrumentError, ValueError) as exc:
            out.append(Added(missing.isin, data.name, "failed", str(exc)))
            continue
        if not instrument.manual:
            enqueue(db, "backfill", {"listing_id": listing.id})
        out.append(Added(missing.isin, instrument.name, "manual" if by_hand else "added", detail))
    db.flush()
    order = {m.isin: n for n, m in enumerate(items)}
    return sorted(out, key=lambda a: order.get(a.isin, 0))
