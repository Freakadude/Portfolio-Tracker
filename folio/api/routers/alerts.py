"""Price alerts on held or watched instruments (FR-INS-05)."""

import datetime as dt
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.audit import write_audit
from folio.db.base import utcnow
from folio.db.models_ledger import Instrument
from folio.db.models_strategy import PriceAlert
from folio.instruments import primary_listing
from folio.marketdata.prices import PriceService
from folio.notify.alerts import crossed

router = APIRouter(prefix="/price-alerts", tags=["alerts"])


class AlertOut(BaseModel):
    id: int
    instrument_id: int
    instrument_name: str
    currency: str | None
    condition: str
    threshold: Decimal
    note: str | None
    active: bool
    armed: bool
    last_fired_at: dt.datetime | None
    last_close: Decimal | None
    met_now: bool | None  # is the latest close already past the level


class AlertIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument_id: int
    condition: Literal["above", "below"]
    threshold: Decimal = Field(gt=0)
    note: str | None = Field(default=None, max_length=200)


class AlertChanges(BaseModel):
    model_config = ConfigDict(extra="forbid")

    condition: Literal["above", "below"] | None = None
    threshold: Decimal | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=200)
    active: bool | None = None


def _out(db: Session, alert: PriceAlert) -> AlertOut:
    instrument = db.get(Instrument, alert.instrument_id)
    listing = primary_listing(db, alert.instrument_id)
    bar = None if listing is None else PriceService(db).last_bar(listing.id)
    return AlertOut(
        id=alert.id,
        instrument_id=alert.instrument_id,
        instrument_name="" if instrument is None else instrument.name,
        currency=None if listing is None else listing.currency,
        condition=alert.condition,
        threshold=alert.threshold,
        note=alert.note,
        active=alert.active,
        armed=alert.armed,
        last_fired_at=alert.last_fired_at,
        last_close=None if bar is None else bar.close,
        met_now=None if bar is None else crossed(alert.condition, bar.close, alert.threshold),
    )


def _load(db: Session, alert_id: int) -> PriceAlert:
    alert = db.get(PriceAlert, alert_id)
    if alert is None or alert.deleted_at is not None:
        raise ApiError(404, "Not found", "That alert does not exist.")
    return alert


@router.get("", response_model=list[AlertOut])
def list_alerts(_user: UserDep, db: DbDep, instrument_id: int | None = None) -> list[AlertOut]:
    query = select(PriceAlert).where(PriceAlert.deleted_at.is_(None)).order_by(PriceAlert.id)
    if instrument_id is not None:
        query = query.where(PriceAlert.instrument_id == instrument_id)
    return [_out(db, a) for a in db.scalars(query)]


@router.post("", response_model=AlertOut, status_code=201)
def create_alert(body: AlertIn, _user: UserDep, db: DbDep) -> AlertOut:
    instrument = db.get(Instrument, body.instrument_id)
    if instrument is None or instrument.deleted_at is not None:
        raise ApiError(404, "Not found", "That instrument does not exist.")
    alert = PriceAlert(
        instrument_id=instrument.id,
        condition=body.condition,
        threshold=body.threshold,
        note=body.note,
    )
    # a level the price is already past does not fire at once: it fires on the next crossing
    listing = primary_listing(db, instrument.id)
    bar = None if listing is None else PriceService(db).last_bar(listing.id)
    alert.armed = bar is None or not crossed(body.condition, bar.close, body.threshold)
    db.add(alert)
    db.flush()
    write_audit(db, "user", "price_alert", "create", entity_id=alert.id,
                diff={"instrument": instrument.name, "condition": body.condition,
                      "threshold": str(body.threshold)})  # fmt: skip
    return _out(db, alert)


@router.patch("/{alert_id}", response_model=AlertOut)
def update_alert(alert_id: int, body: AlertChanges, _user: UserDep, db: DbDep) -> AlertOut:
    alert = _load(db, alert_id)
    changes = body.model_dump(exclude_unset=True)
    diff = {}
    for key, value in changes.items():
        if value is None and key != "note":
            continue
        old = getattr(alert, key)
        if old != value:
            diff[key] = {
                "old": None if old is None else str(old),
                "new": None if value is None else str(value),
            }
            setattr(alert, key, value)
    if {"condition", "threshold"} & set(diff):
        # a new level starts afresh, firing on the next crossing, not at once
        listing = primary_listing(db, alert.instrument_id)
        bar = None if listing is None else PriceService(db).last_bar(listing.id)
        alert.armed = bar is None or not crossed(alert.condition, bar.close, alert.threshold)
    if diff:
        write_audit(db, "user", "price_alert", "update", entity_id=alert.id, diff=diff)
    db.flush()
    return _out(db, alert)


@router.delete("/{alert_id}", status_code=204)
def delete_alert(alert_id: int, _user: UserDep, db: DbDep) -> None:
    alert = _load(db, alert_id)
    alert.deleted_at = utcnow()
    write_audit(db, "user", "price_alert", "delete", entity_id=alert.id, diff={})
