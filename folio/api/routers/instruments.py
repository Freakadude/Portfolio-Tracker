from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.db.models_ledger import Instrument, Listing, PriceBar
from folio.instruments import (
    InstrumentChanges,
    InstrumentError,
    InstrumentInUse,
    NewInstrument,
    create_instrument,
    delete_instrument,
    get_instrument,
    primary_listing,
    update_instrument,
)
from folio.jobs.requests import enqueue
from folio.marketdata.base import ProviderError
from folio.marketdata.prices import PriceService, listing_ref
from folio.marketdata.registry import ProviderFactory
from folio.marketdata.resolve import resolve_isin
from folio.marketdata.runtime import make_provider_factory

router = APIRouter(prefix="/instruments", tags=["instruments"])


def get_providers(request: Request, db: DbDep) -> ProviderFactory:
    state = request.app.state
    return make_provider_factory(
        db,
        state.settings,
        state.usage,
        state.breakers,
        state.provider_transport,
        **state.provider_http_options,
    )


ProvidersDep = Annotated[ProviderFactory, Depends(get_providers)]


class ListingOut(BaseModel):
    id: int
    mic: str
    ticker: str
    currency: str
    primary: bool
    provider_symbols: dict[str, str]


class LastClose(BaseModel):
    date: date
    close: Decimal
    source: str
    overridden: bool


class InstrumentOut(BaseModel):
    id: int
    isin: str | None
    name: str
    asset_class: str
    issuer: str | None
    domicile: str | None
    ter_pct: Decimal | None
    distribution: str | None
    tags: list[str]
    coupon_pct: Decimal | None
    maturity_date: date | None
    rating: str | None
    status: str
    manual: bool
    listings: list[ListingOut]
    last_close: LastClose | None
    stale: bool
    region: str | None
    sector: str | None
    sleeve_id: int | None
    is_benchmark: bool


class CandidateOut(BaseModel):
    mic: str
    exchange_name: str
    ticker: str
    currency: str
    currency_confirmed: bool
    confirmed_by: str | None
    usable: bool
    warning: str | None


class ResolutionOut(BaseModel):
    isin: str
    name: str
    asset_class: str
    issuer: str | None
    domicile: str
    candidates: list[CandidateOut]


class PriceOut(BaseModel):
    date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal
    volume: Decimal | None
    source: str
    overridden: bool


class ManualPriceIn(BaseModel):
    date: date
    close: Decimal = Field(gt=0)


def _view(db: Session, instrument: Instrument) -> InstrumentOut:
    listings = list(
        db.scalars(
            select(Listing)
            .where(Listing.instrument_id == instrument.id)
            .order_by(Listing.pricing_primary.desc(), Listing.id)
        )
    )
    last: LastClose | None = None
    stale = False
    if listings:
        service = PriceService(db)
        bar = service.last_bar(listings[0].id)
        if bar is not None:
            last = LastClose(
                date=bar.date, close=bar.close, source=bar.source, overridden=bar.overridden
            )
        stale = service.is_stale(listing_ref(listings[0], instrument.isin), date.today())
    return InstrumentOut(
        id=instrument.id,
        isin=instrument.isin,
        name=instrument.name,
        asset_class=instrument.asset_class,
        issuer=instrument.issuer,
        domicile=instrument.domicile,
        ter_pct=instrument.ter_pct,
        distribution=instrument.distribution,
        tags=list(instrument.tags or []),
        coupon_pct=instrument.coupon_pct,
        maturity_date=instrument.maturity_date,
        rating=instrument.rating,
        status=instrument.status,
        manual=instrument.manual,
        listings=[
            ListingOut(
                id=x.id,
                mic=x.exchange_mic,
                ticker=x.ticker,
                currency=x.currency,
                primary=x.pricing_primary,
                provider_symbols=dict(x.provider_symbols or {}),
            )
            for x in listings
        ],
        last_close=last,
        stale=stale,
        region=instrument.region,
        sector=instrument.sector,
        sleeve_id=instrument.sleeve_id,
        is_benchmark=instrument.is_benchmark,
    )


def _plain(exc: InstrumentError) -> ApiError:
    if isinstance(exc, InstrumentInUse):
        return ApiError(
            409,
            "Instrument in use",
            str(exc),
            blocking_transactions=exc.blocking,
            blocking_total=exc.total,
        )
    return ApiError(
        409 if "already added" in str(exc) else 422, "Cannot change instrument", str(exc)
    )


@router.get("/resolve", response_model=ResolutionOut)
def resolve(isin: str, _user: UserDep, providers: ProvidersDep) -> ResolutionOut:
    try:
        result = resolve_isin(isin, providers.figi(), providers.chain())
    except ValueError as exc:
        raise ApiError(422, "Invalid ISIN", str(exc)) from exc
    except ProviderError as exc:
        raise ApiError(502, "Lookup failed", f"Could not look up this ISIN: {exc}") from exc
    return ResolutionOut(
        isin=result.isin,
        name=result.name,
        asset_class=result.asset_class,
        issuer=result.issuer,
        domicile=result.domicile,
        candidates=[
            CandidateOut(
                mic=c.mic,
                exchange_name=c.exchange_name,
                ticker=c.ticker,
                currency=c.currency,
                currency_confirmed=c.currency_confirmed,
                confirmed_by=c.confirmed_by,
                usable=c.usable,
                warning=c.warning,
            )
            for c in result.candidates
        ],
    )


@router.get("", response_model=list[InstrumentOut])
def list_instruments(
    _user: UserDep,
    db: DbDep,
    status: Annotated[str, Query(pattern="^(active|archived|all)$")] = "active",
) -> list[InstrumentOut]:
    query = select(Instrument).where(Instrument.deleted_at.is_(None)).order_by(Instrument.name)
    if status != "all":
        query = query.where(Instrument.status == status)
    return [_view(db, i) for i in db.scalars(query)]


@router.post("", response_model=InstrumentOut, status_code=201)
def create(body: NewInstrument, _user: UserDep, db: DbDep) -> InstrumentOut:
    try:
        instrument, listing, _ = create_instrument(db, body)
    except ValueError as exc:
        raise (
            _plain(exc)
            if isinstance(exc, InstrumentError)
            else ApiError(422, "Invalid instrument", str(exc))
        ) from exc
    if not instrument.manual:
        enqueue(db, "backfill", {"listing_id": listing.id})  # the worker fetches the history
    return _view(db, instrument)


def _load(db: Session, instrument_id: int) -> Instrument:
    try:
        return get_instrument(db, instrument_id)
    except InstrumentError as exc:
        raise ApiError(404, "Not found", str(exc)) from exc


@router.get("/{instrument_id}", response_model=InstrumentOut)
def read(instrument_id: int, _user: UserDep, db: DbDep) -> InstrumentOut:
    return _view(db, _load(db, instrument_id))


@router.patch("/{instrument_id}", response_model=InstrumentOut)
def patch(instrument_id: int, body: InstrumentChanges, _user: UserDep, db: DbDep) -> InstrumentOut:
    instrument = _load(db, instrument_id)
    try:
        update_instrument(db, instrument, body)
    except InstrumentError as exc:
        raise ApiError(422, "Invalid instrument", str(exc)) from exc
    return _view(db, instrument)


@router.delete("/{instrument_id}", status_code=204)
def delete(instrument_id: int, _user: UserDep, db: DbDep) -> None:
    instrument = _load(db, instrument_id)
    try:
        delete_instrument(db, instrument)
    except InstrumentError as exc:
        raise _plain(exc) from exc


@router.get("/{instrument_id}/prices", response_model=list[PriceOut])
def prices(
    instrument_id: int,
    _user: UserDep,
    db: DbDep,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
) -> list[Any]:
    instrument = _load(db, instrument_id)
    listing = primary_listing(db, instrument.id)
    if listing is None:
        return []
    query = select(PriceBar).where(PriceBar.listing_id == listing.id).order_by(PriceBar.date)
    if from_ is not None:
        query = query.where(PriceBar.date >= from_)
    if to is not None:
        query = query.where(PriceBar.date <= to)
    return list(db.scalars(query.limit(20000)))


@router.post("/{instrument_id}/prices", response_model=PriceOut, status_code=201)
def set_price(instrument_id: int, body: ManualPriceIn, _user: UserDep, db: DbDep) -> Any:
    """Enter or override one close by hand; audited and protected from later fetches."""
    instrument = _load(db, instrument_id)
    listing = primary_listing(db, instrument.id)
    if listing is None:
        raise ApiError(409, "No listing", "This instrument has no listing to price.")
    return PriceService(db).set_manual_price(listing.id, body.date, body.close)
