"""News sources (FR-NW-01): the owner's list, a preview before saving, and fetch now."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.db.base import utcnow
from folio.db.models_insight import NewsItem, NewsSource
from folio.jobs.requests import enqueue
from folio.marketdata.base import ProviderError
from folio.marketdata.budget import CircuitBreaker
from folio.marketdata.http import HttpClient
from folio.news import service
from folio.news.feed import FeedError, parse_feed
from folio.news.fetch import Fetcher
from folio.news.service import SourceError, SourceInput

router = APIRouter(prefix="/news", tags=["news"])
PREVIEW_ITEMS = 10
PREVIEW_INTERVAL = 3.0  # seconds between requests to one site from the web process


def get_fetcher(request: Request) -> Fetcher:
    """One fetcher for the web process, so its robots.txt cache and pacing persist."""
    state = request.app.state
    if getattr(state, "news_fetcher", None) is None:

        def client_for(domain: str) -> HttpClient:
            return HttpClient(
                "news",
                usage=state.usage,
                breaker=state.breakers.setdefault(f"news:{domain}", CircuitBreaker()),
                transport=state.provider_transport,
                **state.provider_http_options,
            )

        state.news_fetcher = Fetcher(client_for, clock=utcnow, min_interval=PREVIEW_INTERVAL)
    fetcher: Fetcher = state.news_fetcher
    return fetcher


FetcherDep = Annotated[Fetcher, Depends(get_fetcher)]


class SourceIn(BaseModel):
    name: str
    kind: str = "rss"
    url: str = ""
    language: str = "en"
    trust_weight: Decimal = Decimal("0.7")
    poll_minutes: int = 60
    enabled: bool = True
    macro_series: list[str] = Field(default_factory=list)


class SourceOut(BaseModel):
    id: int
    name: str
    kind: str
    url: str
    language: str
    trust_weight: Decimal
    poll_minutes: int
    enabled: bool
    macro_series: list[str]
    items: int
    last_fetch_at: datetime | None
    next_fetch_at: datetime | None
    failures: int
    last_error: str | None


class PreviewIn(BaseModel):
    url: str


class PreviewItemOut(BaseModel):
    title: str
    summary: str
    url: str
    published: datetime


class PreviewOut(BaseModel):
    items: list[PreviewItemOut]
    total: int  # items in the feed


def _out(db: DbDep, source: NewsSource) -> SourceOut:
    count = db.scalar(select(func.count()).where(NewsItem.source_id == source.id)) or 0
    return SourceOut(
        id=source.id,
        name=source.name,
        kind=source.kind,
        url=source.url,
        language=source.language,
        trust_weight=source.trust_weight,
        poll_minutes=source.poll_minutes,
        enabled=source.enabled,
        macro_series=list(source.macro_series or []),
        items=count,
        last_fetch_at=source.last_fetch_at,
        next_fetch_at=source.next_fetch_at,
        failures=source.failures,
        last_error=source.last_error,
    )


def _input(body: SourceIn) -> SourceInput:
    return SourceInput(
        body.name,
        body.kind,
        body.url,
        body.language,
        body.trust_weight,
        body.poll_minutes,
        body.enabled,
        body.macro_series,
    )


@router.get("/sources", response_model=list[SourceOut])
def list_sources(_user: UserDep, db: DbDep) -> list[SourceOut]:
    return [_out(db, s) for s in service.list_sources(db)]


@router.post("/sources", response_model=SourceOut, status_code=201)
def add_source(body: SourceIn, _user: UserDep, db: DbDep) -> SourceOut:
    try:
        return _out(db, service.create_source(db, _input(body)))
    except SourceError as exc:
        raise ApiError(422, "Cannot save source", str(exc)) from exc


@router.put("/sources/{source_id}", response_model=SourceOut)
def change_source(source_id: int, body: SourceIn, _user: UserDep, db: DbDep) -> SourceOut:
    try:
        return _out(db, service.update_source(db, source_id, _input(body)))
    except SourceError as exc:
        raise ApiError(
            404 if "does not exist" in str(exc) else 422, "Cannot save source", str(exc)
        ) from exc


@router.delete("/sources/{source_id}", status_code=204)
def remove_source(source_id: int, _user: UserDep, db: DbDep) -> None:
    try:
        service.delete_source(db, source_id, utcnow())
    except SourceError as exc:
        raise ApiError(404, "Not found", str(exc)) from exc


@router.post("/sources/preview", response_model=PreviewOut)
def preview(body: PreviewIn, _user: UserDep, fetcher: FetcherDep) -> PreviewOut:
    """The latest items of a feed address, before it is saved (FR-NW-01). Nothing is stored."""
    try:
        service.check(SourceInput("preview", url=body.url))
    except SourceError as exc:
        raise ApiError(422, "Cannot read feed", str(exc)) from exc
    try:
        fetched = fetcher.get(body.url.strip())
        items = parse_feed(fetched.body, utcnow())
    except (ProviderError, FeedError) as exc:
        raise ApiError(422, "Cannot read feed", str(exc)) from exc
    newest = sorted(items, key=lambda i: i.published, reverse=True)[:PREVIEW_ITEMS]
    return PreviewOut(
        items=[
            PreviewItemOut(title=i.title, summary=i.summary, url=i.url, published=i.published)
            for i in newest
        ],
        total=len(items),
    )


@router.post("/sources/{source_id}/fetch", status_code=202)
def fetch_now(source_id: int, _user: UserDep, db: DbDep) -> dict[str, str]:
    """Ask the worker to fetch this source now."""
    try:
        service.get_source(db, source_id)
    except SourceError as exc:
        raise ApiError(404, "Not found", str(exc)) from exc
    enqueue(db, "news", {"source_id": source_id})
    return {"status": "queued"}
