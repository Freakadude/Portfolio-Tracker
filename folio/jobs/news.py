"""The news job (FR-NW-01, FR-NW-02): fetches every source that is due and stores new items.

Feeds are fetched politely (conditional requests, robots.txt, a pause between requests to one
site) and a failing source backs off. EODHD's news costs calls of the same daily budget as the
closes, so it only runs while enough is left for them. The SEC filings source and RSS addresses
with `{symbol}` read per followed holding (held or watched), for the companies SEC knows: SEC asks
for a contact address in the User-Agent, so both wait until the owner has given one (ADR 0062).
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.db.models_analytics import Watchlist, WatchlistItem
from folio.db.models_insight import NewsItem, NewsSource
from folio.db.models_ledger import Instrument
from folio.display import small
from folio.instruments import primary_listing
from folio.jobs.context import JobContext
from folio.jobs.runner import JobLog, JobResult, run_job
from folio.marketdata.base import ProviderError
from folio.marketdata.eodhd import NEWS_WEIGHT
from folio.marketdata.prices import tracked_listings
from folio.marketdata.quotes import EOD_MARGIN, listing_refs
from folio.news import sec
from folio.news.assess import assess_news
from folio.news.eodhd import parse_eodhd_news
from folio.news.feed import FeedError, FeedItem, parse_feed
from folio.news.fetch import Fetcher
from folio.news.normalize import canonical_url
from folio.news.pipeline import cluster_and_link
from folio.news.service import (
    SYMBOL,
    due_sources,
    get_source,
    record_failure,
    record_success,
    store_items,
)
from folio.positions import load_positions
from folio.settings_schema import NewsSettings
from folio.settings_store import load_section

LOUD_AFTER = 3  # consecutive failures before the run is marked failed on the System page
MAX_SYMBOLS = 20  # holdings read per run by a per-symbol feed (10 s apart on one site)
COMPANIES_TTL = timedelta(hours=24)


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


def _followed(db: Session) -> list[tuple[Instrument, str | None]]:
    """The instruments news is read for per holding: what is held, and what is watched, with the
    ticker of each one's primary listing."""
    rows, _totals = load_positions(db, group_by_isin=False)
    ids = {r.instrument.id for r in rows if r.state.quantity > 0}
    ids |= set(
        db.scalars(
            select(WatchlistItem.instrument_id)
            .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
            .where(Watchlist.deleted_at.is_(None))
        )
    )
    out: list[tuple[Instrument, str | None]] = []
    for instrument in db.scalars(
        select(Instrument)
        .where(Instrument.id.in_(sorted(ids)), Instrument.deleted_at.is_(None))
        .order_by(Instrument.id)
    ):
        listing = primary_listing(db, instrument.id)
        out.append((instrument, None if listing is None else listing.ticker))
    return out


def _sec_headers(db: Session, log: JobLog, name: str) -> dict[str, str] | None:
    email = NewsSettings.model_validate(load_section(db, "news").model_dump()).sec_contact_email
    if not email:
        log.info(
            f"{name}: skipped, it needs your contact email (Settings, News). SEC asks every "
            "automated reader for one."
        )
        return None
    return {"User-Agent": sec.user_agent(email)}


def _sec_companies(
    fetcher: Fetcher, now: datetime, headers: dict[str, str]
) -> dict[str, sec.Company]:
    """SEC's list of companies by ticker, fetched at most once a day."""
    cached = fetcher.memo.get("sec_companies")
    if cached is not None and now - cached[0] < COMPANIES_TTL:
        return cached[1]  # type: ignore[return-value]
    fetched = fetcher.get(sec.TICKERS_URL, headers=headers)
    try:
        companies = sec.companies_from(json.loads(fetched.body))
    except ValueError as exc:
        raise FeedError(f"SEC's company list could not be read ({exc}).") from exc
    fetcher.memo["sec_companies"] = (now, companies)
    return companies


def _with_sec(
    db: Session, fetcher: Fetcher, now: datetime, headers: dict[str, str]
) -> list[tuple[Instrument, sec.Company]]:
    companies = _sec_companies(fetcher, now, headers)
    pairs: list[tuple[Instrument, sec.Company]] = []
    for instrument, ticker in _followed(db):
        company = sec.company_for(companies, ticker, instrument.name)
        if company is not None:
            pairs.append((instrument, company))
    return pairs


def _sec_items(
    db: Session, fetcher: Fetcher, source: NewsSource, now: datetime, log: JobLog
) -> list[FeedItem] | None:
    """The new SEC filings of the held and watched companies, or None when it was skipped."""
    headers = _sec_headers(db, log, source.name)
    if headers is None:
        return None
    since = sec.since_for(source.last_fetch_at, now)
    items: list[FeedItem] = []
    for instrument, company in _with_sec(db, fetcher, now, headers):
        try:
            data = json.loads(
                fetcher.get(sec.SUBMISSIONS_URL.format(cik=company.cik), headers=headers).body
            )
        except (ProviderError, ValueError) as exc:
            log.info(f"{source.name}: {company.title} could not be read ({exc}).")
            continue
        for filing in sec.filings_from(data, since):
            url = canonical_url(filing.index_url(company.cik))
            if db.scalar(select(NewsItem.id).where(NewsItem.canonical_url == url)) is not None:
                continue  # stored on an earlier run: no need to read the document again
            try:
                document = fetcher.get(filing.document_url(company.cik), headers=headers).body
                text: str | None = document.decode("utf-8", "replace")
            except ProviderError:
                text = None  # the headline is still built from the form
            items.append(sec.item_for(instrument.id, instrument.name, company, filing, text))
    return items


def _per_symbol_items(
    db: Session, fetcher: Fetcher, source: NewsSource, now: datetime, log: JobLog
) -> list[FeedItem] | None:
    """An RSS address with {symbol}, read for each followed holding that has a US symbol (an
    unknown symbol gets general market news from such sites, so only symbols SEC confirms are
    asked). Each item is tagged with its holding. None when it was skipped."""
    headers = _sec_headers(db, log, source.name)
    if headers is None:
        return None
    pairs = _with_sec(db, fetcher, now, headers)[:MAX_SYMBOLS]
    items: dict[str, FeedItem] = {}
    failures: list[str] = []
    for instrument, company in pairs:
        url = source.url.replace(SYMBOL, quote(company.ticker))
        try:
            entries = parse_feed(fetcher.get(url).body, now)
        except (ProviderError, FeedError) as exc:
            failures.append(f"{company.ticker}: {exc}")
            continue
        for entry in entries:
            old = items.get(entry.url)
            tag = f"instrument:{instrument.id}"
            items[entry.url] = replace(old or entry, symbols=(*(old or entry).symbols, tag))
    if failures:
        log.info(f"{source.name}: " + "; ".join(failures[:5]))
        if len(failures) == len(pairs):
            raise ProviderError(failures[-1])
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
                if source.kind in ("eodhd", "sec") or SYMBOL in source.url:
                    if source.kind == "eodhd":
                        items = _eodhd_items(ctx, db, now, log, source.name)
                    elif source.kind == "sec":
                        items = _sec_items(db, fetcher, source, now, log)
                    else:
                        items = _per_symbol_items(db, fetcher, source, now, log)
                    if items is None:
                        record_success(source, now, None, None)
                        db.commit()
                        continue
                    etag = modified = None
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

        grouped = cluster_and_link(db, now)  # no outside calls from here on
        db.commit()
        if grouped.items:
            log.info(
                f"{grouped.items} new items grouped into {grouped.new_clusters} new stories, "
                f"{grouped.links} links to your holdings"
            )

        # then the LLM reads what matters (skipped when the agent is off or has no key)
        llm = ctx.llm_for(db)
        if llm is not None:
            triaged = assess_news(db, llm, now)
            if triaged.assessed or triaged.escalated:
                log.info(
                    f"News triage: {triaged.assessed} stories assessed, {triaged.escalated} "
                    f"re-assessed by the stronger model, {triaged.links_added} links added, "
                    f"{triaged.notified} notified ({small(triaged.cost_eur)} EUR)"
                )
            for problem in triaged.problems:
                (log.error if triaged.stopped in ("auth", "billing") else log.info)(
                    f"News triage: {problem}"
                )
            if triaged.stopped and triaged.stopped not in ("auth", "billing"):
                log.info(f"News triage paused ({triaged.stopped}); the rest waits for next time.")

    return run_job(ctx, "news", body, {"source_id": source_id})
