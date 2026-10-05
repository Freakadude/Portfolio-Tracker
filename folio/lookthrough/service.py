"""Storing and reading ETF holdings snapshots (FR-MD-09)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from folio.audit import write_audit
from folio.db.models_insight import EtfConstituent, EtfSnapshot
from folio.lookthrough.parse import Constituent, HoldingsRead

SOURCES = ("csv", "url", "eodhd")


class HoldingsError(ValueError):
    """The holdings cannot be stored; the message is for the owner."""


@dataclass(frozen=True)
class Snapshot:
    """One ETF's holdings on one date, as the analytics read them."""

    id: int
    instrument_id: int
    as_of: date
    source: str
    covered_pct: Decimal
    constituents: tuple[Constituent, ...]


def store_snapshot(
    db: Session,
    instrument_id: int,
    read: HoldingsRead,
    as_of: date,
    source: str,
    file_name: str | None = None,
    actor: str = "user",
) -> EtfSnapshot:
    """Add a snapshot. The same ETF, date and source replaces the earlier one, so uploading a
    corrected file the same day does not double anything."""
    if read.errors:
        raise HoldingsError(read.errors[0])
    if not read.constituents:
        raise HoldingsError("There are no holdings to store.")
    existing = db.scalar(
        select(EtfSnapshot).where(
            EtfSnapshot.instrument_id == instrument_id,
            EtfSnapshot.as_of == as_of,
            EtfSnapshot.source == source,
        )
    )
    replaced = existing is not None
    if existing is not None:
        db.execute(delete(EtfConstituent).where(EtfConstituent.snapshot_id == existing.id))
        existing.covered_pct = read.covered_pct
        existing.file_name = file_name
        snapshot = existing
    else:
        snapshot = EtfSnapshot(
            instrument_id=instrument_id,
            as_of=as_of,
            source=source,
            file_name=file_name,
            covered_pct=read.covered_pct,
        )
        db.add(snapshot)
    db.flush()
    db.add_all(
        EtfConstituent(
            snapshot_id=snapshot.id,
            name=c.name[:200],
            isin=c.isin,
            ticker=c.ticker[:30] if c.ticker else None,
            weight_pct=c.weight_pct,
            sector=c.sector[:60] if c.sector else None,
            country=c.country[:60] if c.country else None,
            currency=c.currency,
        )
        for c in read.constituents
    )
    db.flush()
    write_audit(
        db,
        actor,
        "etf_snapshot",
        "replace" if replaced else "create",
        entity_id=snapshot.id,
        diff={
            "instrument_id": instrument_id,
            "as_of": as_of.isoformat(),
            "source": source,
            "constituents": len(read.constituents),
        },
    )
    return snapshot


def delete_snapshot(db: Session, snapshot_id: int, actor: str = "user") -> None:
    snapshot = db.get(EtfSnapshot, snapshot_id)
    if snapshot is None:
        raise HoldingsError("That snapshot does not exist.")
    db.execute(delete(EtfConstituent).where(EtfConstituent.snapshot_id == snapshot_id))
    write_audit(
        db,
        actor,
        "etf_snapshot",
        "delete",
        entity_id=snapshot_id,
        diff={"instrument_id": snapshot.instrument_id, "as_of": snapshot.as_of.isoformat()},
    )
    db.delete(snapshot)


def _load(db: Session, rows: Sequence[EtfSnapshot]) -> list[Snapshot]:
    out: list[Snapshot] = []
    for row in rows:
        constituents = db.scalars(
            select(EtfConstituent)
            .where(EtfConstituent.snapshot_id == row.id)
            .order_by(EtfConstituent.id)
        )
        out.append(
            Snapshot(
                id=row.id,
                instrument_id=row.instrument_id,
                as_of=row.as_of,
                source=row.source,
                covered_pct=row.covered_pct,
                constituents=tuple(
                    Constituent(
                        name=c.name,
                        weight_pct=c.weight_pct,
                        isin=c.isin,
                        ticker=c.ticker,
                        sector=c.sector,
                        country=c.country,
                        currency=c.currency,
                    )
                    for c in constituents
                ),
            )
        )
    return out


def list_snapshots(db: Session, instrument_id: int) -> list[EtfSnapshot]:
    return list(
        db.scalars(
            select(EtfSnapshot)
            .where(EtfSnapshot.instrument_id == instrument_id)
            .order_by(EtfSnapshot.as_of.desc(), EtfSnapshot.id.desc())
        )
    )


def latest_snapshots(
    db: Session, instrument_ids: Sequence[int], on: date | None = None
) -> dict[int, Snapshot]:
    """The newest snapshot of each ETF on or before `on` (today when omitted)."""
    out: dict[int, Snapshot] = {}
    for instrument_id in instrument_ids:
        stmt = select(EtfSnapshot).where(EtfSnapshot.instrument_id == instrument_id)
        if on is not None:
            stmt = stmt.where(EtfSnapshot.as_of <= on)
        row = db.scalars(stmt.order_by(EtfSnapshot.as_of.desc(), EtfSnapshot.id.desc())).first()
        if row is not None:
            out[instrument_id] = _load(db, [row])[0]
    return out
