"""The news job (FR-NW-01, FR-NW-02): fetches every source that is due and stores new items.

Feeds are fetched politely (conditional requests, robots.txt, a pause between requests to one
site) and a failing source backs off. EODHD's news costs calls of the same daily budget as the
closes, so it only runs while enough is left for them.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from folio.db.models_insight import NewsSource
from folio.jobs.context import JobContext
from folio.jobs.runner import JobLog, JobResult, run_job
from folio.marketdata.base import ProviderError
from folio.marketdata.eodhd import NEWS_WEIGHT
from folio.marketdata.prices import tracked_listings
from folio.marketdata.quotes import EOD_MARGIN, listing_refs
from folio.news.eodhd import parse_eodhd_news
from folio.news.feed import FeedError, FeedItem, parse_feed
from folio.news.service import (
    due_sources,
    get_source,
    record_failure,
    record_success,
    store_items,
)

LOUD_AFTER = 3  # consecutive failures before the run is marked failed on the System page


def _eodhd_items(
    ctx: JobContext, db: Session, now: datetime, log: JobLog, name: str
) -> list[FeedItem] | None:
    """News for the held tickers, or None when it was skipped (no key, or the budget is kept for
    the closes)."""
    provider = ctx.eodhd_for(db)
    if provider is None:
        log.info(f"{name}: skipped, it needs an EODHD API key (Settings, Providers).")
        return None
    tracked = tracked_listings(db)
    remaining = None if ctx.usage is None else ctx.usage.remaining("eodhd")
    reserve = len(tracked) + EOD_MARGIN  # the nightly closes come first
    items: dict[str, FeedItem] = {}
    for ref in listing_refs(tracked):
        if remaining is not None and remaining - NEWS_WEIGHT < reserve:
            log.info(f"{name}: stopped, the rest of today's EODHD budget is kept for the closes.")
            break
        if ref.provider_symbols.get("eodhd") is None:
            continue
        for item in parse_eodhd_news(provider.get_news(ref), now):
            items.setdefault(item.url, item)
        if remaining is not None:
            remaining -= NEWS_WEIGHT
    return sorted(items.values(), key=lambda i: (i.published, i.url))


def news_job(ctx: JobContext, source_id: int | None = None) -> JobResult:
    def body(db: Session, log: JobLog) -> None:
        fetcher = ctx.fetcher_for()
        now = ctx.now()
        sources = [get_source(db, source_id)] if source_id is not None else due_sources(db, now)
        ids = [s.id for s in sources]
        db.commit()  # the ready-made sources are written once, before any call is made
        if fetcher is None:
            log.error("News fetching is not set up in this process.")
            return
        for sid in ids:
            source = db.get(NewsSource, sid)
            if source is None:
                continue
            etag, modified = source.etag, source.last_modified
            try:
                if source.kind == "eodhd":
                    items = _eodhd_items(ctx, db, now, log, source.name)
                    if items is None:
                        record_success(source, now, None, None)
                        db.commit()
                        continue
                else:
                    fetched = fetcher.get(source.url, source.etag, source.last_modified)
                    if fetched.status == "not_modified":
                        record_success(source, now, etag, modified)
                        db.commit()
                        log.info(f"{source.name}: not modified")
                        continue
                    etag, modified = fetched.etag, fetched.last_modified
                    items = parse_feed(fetched.body, now)
            except (ProviderError, FeedError) as exc:
                record_failure(source, now, str(exc))
                message = f"{source.name}: {exc} (failure {source.failures})"
                db.commit()
                (log.error if source.failures >= LOUD_AFTER else log.info)(message)
                continue
            stored = store_items(db, source, items)
            record_success(source, now, etag, modified)
            db.commit()
            log.info(f"{source.name}: {stored.new} new, {stored.seen} already stored")

    return run_job(ctx, "news", body, {"source_id": source_id})
