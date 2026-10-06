"""Instruments and their listings: create from a resolved candidate or by hand, edit, archive,
delete (FR-INS-01..03). Every change is written to the audit log."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from folio.audit import write_audit
from folio.db.base import utcnow
from folio.db.models import Account
from folio.db.models_analytics import Sleeve, WatchlistItem
from folio.db.models_ledger import Instrument, LedgerTransaction, Listing
from folio.marketdata import exchanges
from folio.marketdata.isin import normalize_isin

AssetClass = Literal["ETF", "ETC", "EQUITY", "BOND", "FUND", "CASH", "OTHER"]
MANUAL_MIC = "MANUAL"
_CURRENCY = re.compile(r"^[A-Z]{3}$")


class InstrumentError(ValueError):
    """Something the owner can fix; the message is written for them."""


class InstrumentInUse(InstrumentError):
    def __init__(self, instrument_name: str, total: int, blocking: list[dict[str, Any]]) -> None:
        self.total = total
        self.blocking = blocking
        super().__init__(
            f"{instrument_name} cannot be deleted: {total} transaction"
            f"{'s' if total != 1 else ''} still use it. Delete those first, or archive the "
            "instrument instead."
        )


class InstrumentFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    asset_class: AssetClass
    issuer: str | None = Field(default=None, max_length=100)
    domicile: str | None = Field(default=None, min_length=2, max_length=2)
    ter_pct: Decimal | None = Field(default=None, ge=0, le=100)
    distribution: Literal["ACC", "DIST"] | None = None
    tags: list[str] = Field(default_factory=list)
    coupon_pct: Decimal | None = Field(default=None, ge=0, le=100)
    maturity_date: date | None = None
    rating: str | None = Field(default=None, max_length=10)
    region: str | None = Field(default=None, max_length=40)
    sector: str | None = Field(default=None, max_length=60)
    sleeve_id: int | None = None
    is_benchmark: bool | None = None  # None means no

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Give the instrument a name.")
        return v

    @field_validator("domicile")
    @classmethod
    def _domicile(cls, v: str | None) -> str | None:
        return None if v is None else v.upper()


class ListingChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mic: str
    ticker: str = Field(min_length=1, max_length=30)
    currency: str

    @field_validator("currency")
    @classmethod
    def _currency(cls, v: str) -> str:
        v = v.strip().upper()
        if not _CURRENCY.match(v):
            raise ValueError("A currency is a three-letter code such as EUR or USD.")
        return v


class NewInstrument(InstrumentFields):
    isin: str | None = None
    listing: ListingChoice | None = None  # the pricing listing picked from the resolver
    manual: bool = False  # no market data: the owner enters prices by hand
    currency: str | None = None  # manual instruments only

    @model_validator(mode="after")
    def _check(self) -> NewInstrument:
        if self.manual:
            if not self.currency or not _CURRENCY.match(self.currency.upper()):
                raise ValueError("A hand-priced instrument needs a currency such as EUR.")
        elif self.isin is None or self.listing is None:
            raise ValueError("Pick a listing for this ISIN, or add the instrument by hand.")
        return self


def _web_address(value: str | None) -> str | None:
    """A saved link must be a plain web address; empty clears it."""
    if value is None or not value.strip():
        return None
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or len(value) > 500:
        raise ValueError("Enter a web address that starts with http:// or https://.")
    return value


class InstrumentChanges(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    asset_class: AssetClass | None = None
    issuer: str | None = None
    product_url: str | None = None  # the issuer's page for this fund
    domicile: str | None = Field(default=None, min_length=2, max_length=2)
    ter_pct: Decimal | None = Field(default=None, ge=0, le=100)
    distribution: Literal["ACC", "DIST"] | None = None
    tags: list[str] | None = None
    coupon_pct: Decimal | None = Field(default=None, ge=0, le=100)
    maturity_date: date | None = None
    rating: str | None = Field(default=None, max_length=10)
    status: Literal["active", "archived"] | None = None
    region: str | None = Field(default=None, max_length=40)
    sector: str | None = Field(default=None, max_length=60)
    sleeve_id: int | None = None
    is_benchmark: bool | None = None

    @field_validator("product_url")
    @classmethod
    def _address(cls, value: str | None) -> str | None:
        return _web_address(value)


_FIELDS = (
    "name",
    "asset_class",
    "issuer",
    "product_url",
    "domicile",
    "ter_pct",
    "distribution",
    "tags",
    "coupon_pct",
    "maturity_date",
    "rating",
    "status",
    "region",
    "sector",
    "sleeve_id",
    "is_benchmark",
)


def _snapshot(instrument: Instrument) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in _FIELDS:
        value = getattr(instrument, key)
        out[key] = (
            value.isoformat()
            if isinstance(value, date)
            else (str(value) if isinstance(value, Decimal) else value)
        )
    return out


def _slug(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", text.upper())[:30] or "PRIVATE"


def _check_sleeve(db: Session, sleeve_id: int | None) -> None:
    if sleeve_id is None:
        return
    sleeve = db.get(Sleeve, sleeve_id)
    if sleeve is None or sleeve.deleted_at is not None:
        raise InstrumentError("That sleeve does not exist. Add it under Settings, Sleeves first.")


def get_instrument(db: Session, instrument_id: int) -> Instrument:
    instrument = db.get(Instrument, instrument_id)
    if instrument is None or instrument.deleted_at is not None:
        raise InstrumentError("That instrument does not exist.")
    return instrument


def primary_listing(db: Session, instrument_id: int) -> Listing | None:
    return db.scalars(
        select(Listing)
        .where(Listing.instrument_id == instrument_id)
        .order_by(Listing.pricing_primary.desc(), Listing.id)
        .limit(1)
    ).first()


def create_instrument(
    db: Session, data: NewInstrument, actor: str = "user"
) -> tuple[Instrument, Listing, bool]:
    """Create (or restore a deleted instrument with the same ISIN). Returns the instrument, its
    pricing listing, and whether it was newly created. The caller queues the price backfill."""
    isin = normalize_isin(data.isin) if data.isin else None
    fields = data.model_dump(include=set(_FIELDS) - {"status"})
    _check_sleeve(db, data.sleeve_id)
    fields["is_benchmark"] = bool(fields.get("is_benchmark"))
    existing = (
        db.scalar(select(Instrument).where(Instrument.isin == isin)) if isin is not None else None
    )
    if existing is not None and existing.deleted_at is None:
        raise InstrumentError(
            f"{isin} is already added as {existing.name}. Edit that instrument instead."
        )

    if data.manual:
        mic, ticker = MANUAL_MIC, _slug(isin or data.name)
        currency = (data.currency or "EUR").upper()
        symbols: dict[str, str] = {}
    else:
        if data.listing is None:  # NewInstrument validation makes this unreachable
            raise InstrumentError("Pick a listing for this ISIN.")
        mic, ticker, currency = data.listing.mic, data.listing.ticker, data.listing.currency
        if mic not in exchanges.EXCHANGES:
            raise InstrumentError(
                f"Folio cannot price listings on exchange {mic} yet. Pick another listing or add "
                "the instrument by hand."
            )
        symbols = exchanges.provider_symbols(mic, ticker)

    created = existing is None
    if existing is None:
        instrument = Instrument(isin=isin, manual=data.manual, status="active", **fields)
        db.add(instrument)
    else:  # restore: the history under this ISIN comes back with it
        instrument = existing
        instrument.deleted_at = None
        instrument.status = "active"
        instrument.manual = data.manual
        for key, value in fields.items():
            setattr(instrument, key, value)
    db.flush()

    listing = db.scalar(
        select(Listing).where(
            Listing.instrument_id == instrument.id,
            Listing.exchange_mic == mic,
            Listing.ticker == ticker,
        )
    )
    for other in db.scalars(select(Listing).where(Listing.instrument_id == instrument.id)):
        other.pricing_primary = False
    if listing is None:
        listing = Listing(
            instrument_id=instrument.id, exchange_mic=mic, ticker=ticker, currency=currency
        )
        db.add(listing)
    listing.currency = currency
    listing.provider_symbols = symbols
    listing.pricing_primary = True
    db.flush()

    write_audit(
        db,
        actor,
        "instrument",
        "create" if created else "restore",
        entity_id=instrument.id,
        diff={"isin": isin, "listing": f"{mic}:{ticker} {currency}", **_snapshot(instrument)},
    )
    return instrument, listing, created


def update_instrument(
    db: Session, instrument: Instrument, changes: InstrumentChanges, actor: str = "user"
) -> dict[str, Any]:
    before = _snapshot(instrument)
    given = changes.model_dump(exclude_unset=True)
    if given.get("is_benchmark") is None:
        given.pop("is_benchmark", None)  # a flag cannot be unset to nothing
    _check_sleeve(db, given.get("sleeve_id"))
    for key, value in given.items():
        if key == "domicile" and value is not None:
            value = value.upper()
        setattr(instrument, key, value)
    db.flush()
    after = _snapshot(instrument)
    diff = {k: {"old": before[k], "new": after[k]} for k in after if before[k] != after[k]}
    if diff:
        write_audit(db, actor, "instrument", "update", entity_id=instrument.id, diff=diff)
    return diff


def blocking_transactions(
    db: Session, instrument_id: int, limit: int = 20
) -> tuple[int, list[dict[str, Any]]]:
    live = (
        LedgerTransaction.instrument_id == instrument_id,
        LedgerTransaction.deleted_at.is_(None),
    )
    total = db.scalar(select(func.count()).select_from(LedgerTransaction).where(*live)) or 0
    rows = db.execute(
        select(LedgerTransaction, Account.name)
        .join(Account, Account.id == LedgerTransaction.account_id)
        .where(*live)
        .order_by(LedgerTransaction.trade_date.desc(), LedgerTransaction.id.desc())
        .limit(limit)
    )
    return total, [
        {
            "id": tx.id,
            "type": tx.type,
            "trade_date": tx.trade_date.isoformat(),
            "account": account_name,
            "quantity": str(tx.quantity),
        }
        for tx, account_name in rows
    ]


def delete_instrument(db: Session, instrument: Instrument, actor: str = "user") -> None:
    """Soft-delete. Refused while any live transaction still uses the instrument (FR-INS-03).
    Prices and the listing are kept, so adding the same ISIN again restores everything."""
    total, blocking = blocking_transactions(db, instrument.id)
    if total:
        raise InstrumentInUse(instrument.name, total, blocking)
    instrument.deleted_at = utcnow()
    db.execute(delete(WatchlistItem).where(WatchlistItem.instrument_id == instrument.id))
    db.flush()
    write_audit(
        db, actor, "instrument", "delete", entity_id=instrument.id, diff=_snapshot(instrument)
    )
