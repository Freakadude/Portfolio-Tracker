"""Watchlists: instruments tracked but not held, priced like holdings (FR-INS-05).

A watched instrument is an ordinary instrument, so the nightly jobs already price it; the
watchlist only remembers which ones the owner wants to keep an eye on, with a note.
"""

from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.audit import write_audit
from folio.db.base import utcnow
from folio.db.models_analytics import Watchlist, WatchlistItem
from folio.db.models_ledger import Instrument, JobRequest
from folio.instruments import primary_listing
from folio.jobs.requests import enqueue, enqueue_once
from folio.marketdata.prices import PriceService, listing_ref

router = APIRouter(prefix="/watchlists", tags=["watchlists"])


class ItemOut(BaseModel):
    id: int
    instrument_id: int
    name: str
    isin: str | None
    ticker: str | None
    currency: str | None
    note: str | None
    close: Decimal | None
    close_date: date | None
    previous_close: Decimal | None
    stale: bool
    fetching: bool  # the worker has been asked for its prices and has not finished


class WatchlistOut(BaseModel):
    id: int
    name: str
    items: list[ItemOut]


class WatchlistIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)


class ItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument_id: int
    note: str | None = Field(default=None, max_length=500)


class ItemChanges(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=500)


def _waiting(db: Session) -> list[JobRequest]:
    return list(db.scalars(select(JobRequest).where(JobRequest.status.in_(("pending", "running")))))


def _is_fetching(waiting: list[JobRequest], listing_id: int | None) -> bool:
    return any(
        r.job == "refresh"
        or (r.job == "backfill" and (r.params or {}).get("listing_id") == listing_id)
        for r in waiting
    )


def _item_out(
    db: Session, item: WatchlistItem, instrument: Instrument, waiting: list[JobRequest]
) -> ItemOut:
    listing = primary_listing(db, instrument.id)
    close = previous = close_date = None
    stale = False
    if listing is not None:
        service = PriceService(db)
        bar = service.last_bar(listing.id)
        if bar is not None:
            close, close_date = bar.close, bar.date
            earlier = service.last_bar(listing.id, bar.date - timedelta(days=1))
            previous = None if earlier is None else earlier.close
        stale = service.is_stale(listing_ref(listing, instrument.isin), date.today())
    return ItemOut(
        id=item.id,
        instrument_id=instrument.id,
        name=instrument.name,
        isin=instrument.isin,
        ticker=None if listing is None else listing.ticker,
        currency=None if listing is None else listing.currency,
        note=item.note,
        close=close,
        close_date=close_date,
        previous_close=previous,
        stale=stale,
        fetching=listing is not None and _is_fetching(waiting, listing.id),
    )


def _out(db: Session, watchlist: Watchlist) -> WatchlistOut:
    rows = db.execute(
        select(WatchlistItem, Instrument)
        .join(Instrument, Instrument.id == WatchlistItem.instrument_id)
        .where(WatchlistItem.watchlist_id == watchlist.id, Instrument.deleted_at.is_(None))
        .order_by(WatchlistItem.id)
    )
    waiting = _waiting(db)
    return WatchlistOut(
        id=watchlist.id,
        name=watchlist.name,
        items=[_item_out(db, i, ins, waiting) for i, ins in rows],
    )


def _has_prices(db: Session, instrument: Instrument) -> bool:
    listing = primary_listing(db, instrument.id)
    return listing is None or PriceService(db).last_bar(listing.id) is not None


def _fetch_history(db: Session, instrument: Instrument) -> None:
    """Ask the worker for the price history of a watched instrument that has none, so the list
    shows something at once; the nightly and intraday jobs then keep it up to date."""
    listing = primary_listing(db, instrument.id)
    if listing is None or instrument.manual or _has_prices(db, instrument):
        return
    waiting = [r for r in _waiting(db) if r.job == "backfill"]
    if not _is_fetching(waiting, listing.id):
        enqueue(db, "backfill", {"listing_id": listing.id})


def _load(db: Session, watchlist_id: int) -> Watchlist:
    found = db.get(Watchlist, watchlist_id)
    if found is None or found.deleted_at is not None:
        raise ApiError(404, "Not found", "That watchlist does not exist.")
    return found


@router.get("", response_model=list[WatchlistOut])
def list_watchlists(_user: UserDep, db: DbDep) -> list[WatchlistOut]:
    rows = list(
        db.scalars(select(Watchlist).where(Watchlist.deleted_at.is_(None)).order_by(Watchlist.id))
    )
    if not rows:  # the first visit gets the one list most owners need
        first = Watchlist(name="Watchlist")
        db.add(first)
        db.flush()
        rows = [first]
    return [_out(db, w) for w in rows]


@router.post("", response_model=WatchlistOut, status_code=201)
def create_watchlist(body: WatchlistIn, _user: UserDep, db: DbDep) -> WatchlistOut:
    watchlist = Watchlist(name=body.name.strip())
    db.add(watchlist)
    db.flush()
    write_audit(
        db, "user", "watchlist", "create", entity_id=watchlist.id, diff={"name": watchlist.name}
    )
    return _out(db, watchlist)


@router.patch("/{watchlist_id}", response_model=WatchlistOut)
def rename_watchlist(
    watchlist_id: int, body: WatchlistIn, _user: UserDep, db: DbDep
) -> WatchlistOut:
    watchlist = _load(db, watchlist_id)
    old, watchlist.name = watchlist.name, body.name.strip()
    if old != watchlist.name:
        write_audit(
            db,
            "user",
            "watchlist",
            "update",
            entity_id=watchlist.id,
            diff={"name": {"old": old, "new": watchlist.name}},
        )
    return _out(db, watchlist)


@router.delete("/{watchlist_id}", status_code=204)
def delete_watchlist(watchlist_id: int, _user: UserDep, db: DbDep) -> None:
    watchlist = _load(db, watchlist_id)
    watchlist.deleted_at = utcnow()
    write_audit(
        db, "user", "watchlist", "delete", entity_id=watchlist.id, diff={"name": watchlist.name}
    )


@router.post("/{watchlist_id}/items", response_model=WatchlistOut, status_code=201)
def add_item(watchlist_id: int, body: ItemIn, _user: UserDep, db: DbDep) -> WatchlistOut:
    watchlist = _load(db, watchlist_id)
    instrument = db.get(Instrument, body.instrument_id)
    if instrument is None or instrument.deleted_at is not None:
        raise ApiError(404, "Not found", "That instrument does not exist.")
    exists = db.scalar(
        select(WatchlistItem).where(
            WatchlistItem.watchlist_id == watchlist.id,
            WatchlistItem.instrument_id == instrument.id,
        )
    )
    if exists is not None:
        raise ApiError(409, "Already watched", f"{instrument.name} is already on this watchlist.")
    db.add(WatchlistItem(watchlist_id=watchlist.id, instrument_id=instrument.id, note=body.note))
    db.flush()
    write_audit(
        db, "user", "watchlist", "add", entity_id=watchlist.id, diff={"instrument": instrument.name}
    )
    _fetch_history(db, instrument)
    return _out(db, watchlist)


@router.post("/{watchlist_id}/refresh", response_model=WatchlistOut, status_code=202)
def refresh_items(watchlist_id: int, _user: UserDep, db: DbDep) -> WatchlistOut:
    """Fetch prices now for what is on the list: the history of items that have none, and the
    newest closes of all of them."""
    watchlist = _load(db, watchlist_id)
    rows = db.execute(
        select(WatchlistItem, Instrument)
        .join(Instrument, Instrument.id == WatchlistItem.instrument_id)
        .where(WatchlistItem.watchlist_id == watchlist.id, Instrument.deleted_at.is_(None))
    )
    for _item, instrument in rows:
        _fetch_history(db, instrument)
    enqueue_once(db, "refresh")
    return _out(db, watchlist)


def _item(db: Session, watchlist: Watchlist, item_id: int) -> WatchlistItem:
    item = db.get(WatchlistItem, item_id)
    if item is None or item.watchlist_id != watchlist.id:
        raise ApiError(404, "Not found", "That item is not on this watchlist.")
    return item


@router.patch("/{watchlist_id}/items/{item_id}", response_model=WatchlistOut)
def edit_item(
    watchlist_id: int, item_id: int, body: ItemChanges, _user: UserDep, db: DbDep
) -> WatchlistOut:
    watchlist = _load(db, watchlist_id)
    _item(db, watchlist, item_id).note = body.note
    db.flush()
    return _out(db, watchlist)


@router.delete("/{watchlist_id}/items/{item_id}", response_model=WatchlistOut)
def remove_item(watchlist_id: int, item_id: int, _user: UserDep, db: DbDep) -> WatchlistOut:
    watchlist = _load(db, watchlist_id)
    item = _item(db, watchlist, item_id)
    instrument = db.get(Instrument, item.instrument_id)
    db.delete(item)
    db.flush()
    write_audit(
        db,
        "user",
        "watchlist",
        "remove",
        entity_id=watchlist.id,
        diff={"instrument": None if instrument is None else instrument.name},
    )
    return _out(db, watchlist)
