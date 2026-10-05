"""ETF holdings for look-through (FR-MD-09): upload a file or set a download address, preview
how a file is read, store a snapshot, and see what an ETF holds."""

import json
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.api.deps import DbDep, StoreDep, UserDep
from folio.api.errors import ApiError
from folio.db.models_insight import EtfConstituent, EtfSnapshot
from folio.imports.parse import MAX_BYTES, ParseError
from folio.instruments import InstrumentError, get_instrument
from folio.jobs.requests import enqueue
from folio.lookthrough import service
from folio.lookthrough.parse import (
    HoldingsFile,
    HoldingsMapping,
    HoldingsRead,
    read_holdings,
    suggest,
)
from folio.settings_schema import HoldingsSource, LookThroughSettings
from folio.settings_store import load_section, save_section

router = APIRouter(prefix="/instruments", tags=["look-through"])
PREVIEW_ROWS = 20


class ConstituentOut(BaseModel):
    name: str
    isin: str | None
    ticker: str | None
    weight_pct: Decimal
    sector: str | None
    country: str | None
    currency: str | None


class HeaderOut(BaseModel):
    index: int
    label: str


class HoldingsPreviewOut(BaseModel):
    headers: list[HeaderOut]
    mapping: HoldingsMapping
    as_of: date | None
    holdings: int
    covered_pct: Decimal
    top: list[ConstituentOut]
    dropped: list[str]
    warnings: list[str]
    errors: list[str]


class SnapshotOut(BaseModel):
    id: int
    as_of: date
    source: str
    file_name: str | None
    covered_pct: Decimal
    holdings: int
    stale: bool


class HoldingsOut(BaseModel):
    snapshots: list[SnapshotOut]
    top: list[ConstituentOut]  # the newest snapshot's largest holdings
    source: HoldingsSource
    stale_days: int


class StoredOut(BaseModel):
    snapshot: SnapshotOut
    warnings: list[str]


def _etf(db: Session, instrument_id: int) -> None:
    try:
        get_instrument(db, instrument_id)
    except InstrumentError as exc:
        raise ApiError(404, "Not found", str(exc)) from exc


def _constituents(read: HoldingsRead) -> list[ConstituentOut]:
    ranked = sorted(read.constituents, key=lambda c: c.weight_pct, reverse=True)
    return [
        ConstituentOut(
            name=c.name,
            isin=c.isin,
            ticker=c.ticker,
            weight_pct=c.weight_pct,
            sector=c.sector,
            country=c.country,
            currency=c.currency,
        )
        for c in ranked[:PREVIEW_ROWS]
    ]


def _read(data: bytes, mapping_json: str | None) -> tuple[HoldingsFile, HoldingsRead]:
    try:
        file = suggest(data)
    except ParseError as exc:
        raise ApiError(422, "Holdings problem", str(exc)) from exc
    mapping = file.mapping
    if mapping_json:
        try:
            mapping = HoldingsMapping.model_validate(json.loads(mapping_json))
        except ValueError as exc:
            raise ApiError(422, "Holdings problem", "The column mapping is not valid.") from exc
    return file, read_holdings(file, mapping)


def _snapshot_out(db: Session, snapshot: EtfSnapshot, stale_days: int, today: date) -> SnapshotOut:
    count = len(
        db.scalars(select(EtfConstituent.id).where(EtfConstituent.snapshot_id == snapshot.id)).all()
    )
    return SnapshotOut(
        id=snapshot.id,
        as_of=snapshot.as_of,
        source=snapshot.source,
        file_name=snapshot.file_name,
        covered_pct=snapshot.covered_pct,
        holdings=count,
        stale=(today - snapshot.as_of).days > stale_days,
    )


@router.get("/{instrument_id}/holdings", response_model=HoldingsOut)
def holdings(instrument_id: int, _user: UserDep, db: DbDep) -> HoldingsOut:
    _etf(db, instrument_id)
    config = LookThroughSettings.model_validate(load_section(db, "lookthrough").model_dump())
    today = date.today()
    snapshots = service.list_snapshots(db, instrument_id)
    top: list[ConstituentOut] = []
    if snapshots:
        newest = service.latest_snapshots(db, [instrument_id])[instrument_id]
        top = _constituents(
            HoldingsRead(constituents=list(newest.constituents), covered_pct=newest.covered_pct)
        )
    return HoldingsOut(
        snapshots=[_snapshot_out(db, s, config.stale_days, today) for s in snapshots],
        top=top,
        source=config.sources.get(str(instrument_id), HoldingsSource()),
        stale_days=config.stale_days,
    )


@router.post("/{instrument_id}/holdings/preview", response_model=HoldingsPreviewOut)
async def preview(
    instrument_id: int,
    _user: UserDep,
    db: DbDep,
    file: Annotated[UploadFile, File()],
    mapping: Annotated[str | None, Form()] = None,
) -> HoldingsPreviewOut:
    """How the file would be read, with nothing stored. Send `mapping` to try other columns."""
    _etf(db, instrument_id)
    parsed, read = _read(await file.read(MAX_BYTES + 1), mapping)
    used = HoldingsMapping.model_validate(json.loads(mapping)) if mapping else parsed.mapping
    header = parsed.table[used.header_row]
    return HoldingsPreviewOut(
        headers=[HeaderOut(index=i, label=h or f"(column {i + 1})") for i, h in enumerate(header)],
        mapping=used,
        as_of=parsed.as_of,
        holdings=len(read.constituents),
        covered_pct=read.covered_pct,
        top=_constituents(read),
        dropped=read.dropped,
        warnings=read.warnings,
        errors=read.errors,
    )


@router.post("/{instrument_id}/holdings", response_model=StoredOut, status_code=201)
async def upload(
    instrument_id: int,
    _user: UserDep,
    db: DbDep,
    file: Annotated[UploadFile, File()],
    mapping: Annotated[str | None, Form()] = None,
    as_of: Annotated[date | None, Form()] = None,
) -> StoredOut:
    """Store the file as a snapshot, dated by the file itself unless `as_of` says otherwise."""
    _etf(db, instrument_id)
    parsed, read = _read(await file.read(MAX_BYTES + 1), mapping)
    try:
        snapshot = service.store_snapshot(
            db,
            instrument_id,
            read,
            as_of or parsed.as_of or date.today(),
            "csv",
            file.filename,
        )
    except service.HoldingsError as exc:
        raise ApiError(422, "Holdings problem", str(exc)) from exc
    config = LookThroughSettings.model_validate(load_section(db, "lookthrough").model_dump())
    return StoredOut(
        snapshot=_snapshot_out(db, snapshot, config.stale_days, date.today()),
        warnings=read.warnings,
    )


@router.delete("/{instrument_id}/holdings/{snapshot_id}", status_code=204)
def remove(instrument_id: int, snapshot_id: int, _user: UserDep, db: DbDep) -> None:
    _etf(db, instrument_id)
    owned = {s.id for s in service.list_snapshots(db, instrument_id)}
    if snapshot_id not in owned:
        raise ApiError(404, "Not found", "That snapshot does not belong to this instrument.")
    service.delete_snapshot(db, snapshot_id)


@router.put("/{instrument_id}/holdings/source", response_model=HoldingsSource)
def set_source(
    instrument_id: int, body: HoldingsSource, _user: UserDep, db: DbDep, store: StoreDep
) -> HoldingsSource:
    """Where this ETF's holdings are refreshed from each month, besides uploaded files."""
    _etf(db, instrument_id)
    config = LookThroughSettings.model_validate(load_section(db, "lookthrough").model_dump())
    sources = dict(config.sources)
    if body.url or body.eodhd:
        sources[str(instrument_id)] = HoldingsSource(url=body.url or None, eodhd=body.eodhd)
    else:
        sources.pop(str(instrument_id), None)
    save_section(
        db, store, "lookthrough", LookThroughSettings(sources=sources, stale_days=config.stale_days)
    )
    return sources.get(str(instrument_id), HoldingsSource())


@router.post("/{instrument_id}/holdings/refresh", status_code=202)
def refresh(instrument_id: int, _user: UserDep, db: DbDep) -> dict[str, str]:
    """Ask the worker to fetch this ETF's holdings now from its saved source."""
    _etf(db, instrument_id)
    enqueue(db, "lookthrough", {"instrument_id": instrument_id})
    return {"status": "queued"}
