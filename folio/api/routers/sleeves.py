"""Sleeves: owner-defined buckets for instruments, with optional targets (FR-INS-04, Q3)."""

from decimal import Decimal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.audit import write_audit
from folio.db.base import utcnow
from folio.db.models_analytics import Sleeve
from folio.db.models_ledger import Instrument

router = APIRouter(prefix="/sleeves", tags=["sleeves"])


class SleeveOut(BaseModel):
    id: int
    name: str
    target_pct: Decimal | None
    band_pct: Decimal | None
    sort_order: int
    instrument_count: int


class SleeveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=60)
    target_pct: Decimal | None = Field(default=None, ge=0, le=100)
    band_pct: Decimal | None = Field(default=None, ge=0, le=100)


class SleeveChanges(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=60)
    target_pct: Decimal | None = Field(default=None, ge=0, le=100)
    band_pct: Decimal | None = Field(default=None, ge=0, le=100)


class OrderIn(BaseModel):
    ids: list[int]


def _count(db: Session, sleeve_id: int) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Instrument)
            .where(Instrument.sleeve_id == sleeve_id, Instrument.deleted_at.is_(None))
        )
        or 0
    )


def _out(db: Session, sleeve: Sleeve) -> SleeveOut:
    return SleeveOut(
        id=sleeve.id,
        name=sleeve.name,
        target_pct=sleeve.target_pct,
        band_pct=sleeve.band_pct,
        sort_order=sleeve.sort_order,
        instrument_count=_count(db, sleeve.id),
    )


def _load(db: Session, sleeve_id: int) -> Sleeve:
    sleeve = db.get(Sleeve, sleeve_id)
    if sleeve is None or sleeve.deleted_at is not None:
        raise ApiError(404, "Not found", "That sleeve does not exist.")
    return sleeve


def _check_name(db: Session, name: str, ignore_id: int | None = None) -> str:
    name = name.strip()
    if not name:
        raise ApiError(422, "Invalid sleeve", "Give the sleeve a name.")
    for other in db.scalars(select(Sleeve).where(Sleeve.deleted_at.is_(None))):
        if other.id != ignore_id and other.name.lower() == name.lower():
            raise ApiError(409, "Sleeve exists", f"There is already a sleeve called {other.name}.")
    return name


@router.get("", response_model=list[SleeveOut])
def list_sleeves(_user: UserDep, db: DbDep) -> list[SleeveOut]:
    rows = db.scalars(
        select(Sleeve).where(Sleeve.deleted_at.is_(None)).order_by(Sleeve.sort_order, Sleeve.id)
    )
    return [_out(db, s) for s in rows]


@router.post("", response_model=SleeveOut, status_code=201)
def create_sleeve(body: SleeveIn, _user: UserDep, db: DbDep) -> SleeveOut:
    name = _check_name(db, body.name)
    last = db.scalar(select(func.max(Sleeve.sort_order))) or 0
    sleeve = Sleeve(
        name=name, target_pct=body.target_pct, band_pct=body.band_pct, sort_order=last + 1
    )
    db.add(sleeve)
    db.flush()
    write_audit(
        db,
        "user",
        "sleeve",
        "create",
        entity_id=sleeve.id,
        diff={
            "name": name,
            "target_pct": None if body.target_pct is None else str(body.target_pct),
            "band_pct": None if body.band_pct is None else str(body.band_pct),
        },
    )
    return _out(db, sleeve)


@router.put("/order", response_model=list[SleeveOut])
def reorder(body: OrderIn, _user: UserDep, db: DbDep) -> list[SleeveOut]:
    sleeves = {s.id: s for s in db.scalars(select(Sleeve).where(Sleeve.deleted_at.is_(None)))}
    if sorted(body.ids) != sorted(sleeves):
        raise ApiError(422, "Invalid order", "List every sleeve exactly once.")
    for position, sleeve_id in enumerate(body.ids, start=1):
        sleeves[sleeve_id].sort_order = position
    db.flush()
    return [_out(db, sleeves[i]) for i in body.ids]


@router.patch("/{sleeve_id}", response_model=SleeveOut)
def update_sleeve(sleeve_id: int, body: SleeveChanges, _user: UserDep, db: DbDep) -> SleeveOut:
    sleeve = _load(db, sleeve_id)
    diff: dict[str, dict[str, str | None]] = {}
    for key, value in body.model_dump(exclude_unset=True).items():
        if key == "name":
            if value is None:
                continue
            value = _check_name(db, value, ignore_id=sleeve.id)
        old = getattr(sleeve, key)
        if old != value:
            diff[key] = {
                "old": None if old is None else str(old),
                "new": None if value is None else str(value),
            }
            setattr(sleeve, key, value)
    if diff:
        write_audit(db, "user", "sleeve", "update", entity_id=sleeve.id, diff=diff)
    return _out(db, sleeve)


@router.delete("/{sleeve_id}", status_code=204)
def delete_sleeve(sleeve_id: int, _user: UserDep, db: DbDep) -> None:
    sleeve = _load(db, sleeve_id)
    count = _count(db, sleeve.id)
    if count:
        raise ApiError(
            409,
            "Sleeve in use",
            f"{sleeve.name} is set on {count} instrument{'s' if count != 1 else ''}. "
            "Move them to another sleeve first.",
        )
    sleeve.deleted_at = utcnow()
    write_audit(db, "user", "sleeve", "delete", entity_id=sleeve.id, diff={"name": sleeve.name})
