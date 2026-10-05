"""News sources (FR-NW-01): the owner's list, a preview before saving, and fetch now."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, exists, func, select

from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.db.base import utcnow
from folio.db.models_insight import (
    NewsAssessment,
    NewsCluster,
    NewsItem,
    NewsLink,
    NewsSource,
)
from folio.db.models_ledger import Instrument
from folio.jobs.requests import enqueue
from folio.marketdata.base import ProviderError
from folio.marketdata.budget import CircuitBreaker
from folio.marketdata.http import HttpClient
from folio.news import service
from folio.news.feed import FeedError, parse_feed
from folio.news.feedback import FeedbackError, give_feedback
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


class FeedPreviewIn(BaseModel):
    url: str


class FeedPreviewItemOut(BaseModel):
    title: str
    summary: str
    url: str
    published: datetime


class FeedPreviewOut(BaseModel):
    items: list[FeedPreviewItemOut]
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


@router.post("/sources/preview", response_model=FeedPreviewOut)
def preview(body: FeedPreviewIn, _user: UserDep, fetcher: FetcherDep) -> FeedPreviewOut:
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
    return FeedPreviewOut(
        items=[
            FeedPreviewItemOut(title=i.title, summary=i.summary, url=i.url, published=i.published)
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


# --- stories (FR-NW-07) ---------------------------------------------------------------------------


class NewsItemOut(BaseModel):
    id: int
    source: str
    title: str
    summary: str
    url: str
    published: datetime


class NewsLinkOut(BaseModel):
    id: int
    link_type: str  # direct | look_through | macro | theme
    instrument_id: int | None
    sleeve: str | None
    label: str  # the instrument's name, or the sleeve
    weight_pct: Decimal | None  # the company's weight inside the ETF, for look-through
    relevance: Decimal
    matched_by: str


class NewsAssessmentOut(BaseModel):
    impact_score: int
    direction: str
    horizon: str
    affected: list[str]  # names of the holdings it touches
    rationale: str
    confidence: str
    model: str


class NewsClusterOut(BaseModel):
    id: int
    title: str
    first_seen: datetime
    last_seen: datetime
    relevance: Decimal
    items: list[NewsItemOut]
    links: list[NewsLinkOut]
    assessment: NewsAssessmentOut | None


class NewsPageOut(BaseModel):
    clusters: list[NewsClusterOut]
    total: int


class NewsFeedbackIn(BaseModel):
    verdict: str  # useful | not_relevant
    link_id: int | None = None  # for "this link is wrong", else all alias links of the story


class NewsFeedbackChangeOut(BaseModel):
    kind: str  # source_trust | alias_weight
    name: str
    old: Decimal
    new: Decimal


class NewsFeedbackOut(BaseModel):
    changes: list[NewsFeedbackChangeOut]


def _cluster_out(db: DbDep, cluster: NewsCluster, names: dict[int, str]) -> NewsClusterOut:
    sources = {s.id: s.name for s in db.scalars(select(NewsSource))}
    items = db.scalars(
        select(NewsItem).where(NewsItem.cluster_id == cluster.id).order_by(NewsItem.published_at)
    )
    links = db.scalars(
        select(NewsLink)
        .where(NewsLink.cluster_id == cluster.id)
        .order_by(NewsLink.relevance.desc())
    )
    latest = db.scalars(
        select(NewsAssessment)
        .where(NewsAssessment.cluster_id == cluster.id)
        .order_by(NewsAssessment.id.desc())
    ).first()

    def label_of(ref: str) -> str:
        kind, _, ident = ref.partition(":")
        return names.get(int(ident), ref) if kind == "instrument" and ident.isdigit() else ident

    return NewsClusterOut(
        id=cluster.id,
        title=cluster.title,
        first_seen=cluster.first_seen,
        last_seen=cluster.last_seen,
        relevance=cluster.relevance,
        items=[
            NewsItemOut(
                id=i.id,
                source=sources.get(i.source_id, "?"),
                title=i.title,
                summary=i.summary,
                url=i.canonical_url,
                published=i.published_at,
            )
            for i in items
        ],
        links=[
            NewsLinkOut(
                id=k.id,
                link_type=k.link_type,
                instrument_id=k.instrument_id,
                sleeve=k.sleeve,
                label=names.get(k.instrument_id or 0, k.sleeve or "?"),
                weight_pct=k.weight_pct,
                relevance=k.relevance,
                matched_by=k.matched_by,
            )
            for k in links
        ],
        assessment=None
        if latest is None
        else NewsAssessmentOut(
            impact_score=latest.impact_score,
            direction=latest.direction,
            horizon=latest.horizon,
            affected=[label_of(a) for a in (latest.affected or [])],
            rationale=latest.rationale,
            confidence=latest.confidence,
            model=latest.model,
        ),
    )


def _names(db: DbDep) -> dict[int, str]:
    return {i.id: i.name for i in db.scalars(select(Instrument))}


@router.get("", response_model=NewsPageOut)
def list_news(
    _user: UserDep,
    db: DbDep,
    instrument: int | None = None,
    min_impact: Annotated[int | None, Query(ge=0, le=100)] = None,
    direction: str | None = None,
    source: int | None = None,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    include_unlinked: bool = False,
    sort: Annotated[str, Query(pattern="^(time|relevance|impact)$")] = "time",
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> NewsPageOut:
    """Stories, newest first: filter by holding (stories linked to it directly or through an ETF
    that holds the company), impact, direction, source and date."""
    query = select(NewsCluster)
    if not include_unlinked:
        query = query.where(NewsCluster.relevance > 0)
    if instrument is not None:
        query = query.where(
            exists().where(
                NewsLink.cluster_id == NewsCluster.id, NewsLink.instrument_id == instrument
            )
        )
    if source is not None:
        query = query.where(
            exists().where(NewsItem.cluster_id == NewsCluster.id, NewsItem.source_id == source)
        )
    if min_impact is not None:
        query = query.where(NewsCluster.max_impact >= min_impact)
    if direction is not None:
        query = query.where(
            exists().where(
                NewsAssessment.cluster_id == NewsCluster.id, NewsAssessment.direction == direction
            )
        )
    if from_ is not None:
        query = query.where(NewsCluster.last_seen >= datetime.combine(from_, time.min, UTC))
    if to is not None:
        end = datetime.combine(to + timedelta(days=1), time.min, UTC)
        query = query.where(NewsCluster.first_seen < end)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    order: dict[str, ColumnElement[Any]] = {
        "time": NewsCluster.last_seen.desc(),
        "relevance": NewsCluster.relevance.desc(),
        "impact": NewsCluster.max_impact.desc(),
    }
    page = db.scalars(
        query.order_by(order[sort], NewsCluster.id.desc()).limit(limit).offset(offset)
    )
    names = _names(db)
    return NewsPageOut(clusters=[_cluster_out(db, c, names) for c in page], total=total)


@router.get("/clusters/{cluster_id}", response_model=NewsClusterOut)
def one_story(cluster_id: int, _user: UserDep, db: DbDep) -> NewsClusterOut:
    cluster = db.get(NewsCluster, cluster_id)
    if cluster is None:
        raise ApiError(404, "Not found", "That story does not exist.")
    return _cluster_out(db, cluster, _names(db))


@router.post("/clusters/{cluster_id}/feedback", response_model=NewsFeedbackOut)
def feedback(cluster_id: int, body: NewsFeedbackIn, _user: UserDep, db: DbDep) -> NewsFeedbackOut:
    """Useful or not relevant: five net "not relevant" marks lower a source's trust, and a
    wrongly linked story lowers the alias that found it (FR-NW-08)."""
    try:
        changes = give_feedback(db, cluster_id, body.verdict, body.link_id)
    except FeedbackError as exc:
        status = 404 if "does not exist" in str(exc) else 422
        raise ApiError(status, "Cannot record feedback", str(exc)) from exc
    return NewsFeedbackOut(
        changes=[
            NewsFeedbackChangeOut(kind=c.kind, name=c.name, old=c.old, new=c.new) for c in changes
        ]
    )
