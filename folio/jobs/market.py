"""Market-data jobs: nightly closes per exchange, ECB rates, gap repair, instrument backfill."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from folio.db.models_ledger import Instrument, LedgerTransaction, Listing
from folio.events import PRICE_UPDATE, prune_events, publish_event
from folio.jobs.context import JobContext
from folio.jobs.runner import JobLog, JobResult, run_job
from folio.marketdata import exchanges
from folio.marketdata.base import ProviderError
from folio.marketdata.corporate_actions import propose_all
from folio.marketdata.fx import FxService, needed_currencies
from folio.marketdata.macro import MacroService
from folio.marketdata.prices import PriceService, listing_ref, tracked_listings
from folio.marketdata.quotes import (
    EOD_MARGIN,
    QuoteService,
    held_listings,
    listing_refs,
    open_now,
    prune_quotes,
)
from folio.settings_store import load_section

FX_FLOOR_YEARS = 5  # how far back to fetch rates when no transaction needs more
GAP_WINDOW_DAYS = 30
BACKFILL_DEFAULT_DAYS = 365
BACKFILL_LEAD_DAYS = 7  # so the first holding day also has a previous close for day change


def first_transaction_date(db: Session, instrument_id: int | None = None) -> date | None:
    query = select(func.min(LedgerTransaction.trade_date)).where(
        LedgerTransaction.deleted_at.is_(None), LedgerTransaction.status == "posted"
    )
    if instrument_id is not None:
        query = query.where(LedgerTransaction.instrument_id == instrument_id)
    return db.scalar(query)


def eod_job(
    ctx: JobContext, mic: str, day: date | None = None, only_if_tracked: bool = False
) -> JobResult:
    """Fetch the latest closes for every tracked listing on one exchange. On a day the
    exchange is closed nothing is fetched (FR-MD-02). The scheduler passes
    `only_if_tracked`, so exchanges without any of your listings leave no run record."""
    if only_if_tracked:
        with ctx.session_factory() as db:
            if not tracked_listings(db, mic):
                return JobResult(0, "eod", "skipped", f"No tracked listings on {mic}.")
    zone = ZoneInfo(str(exchanges.calendar(mic).tz))
    local_day = day or ctx.now().astimezone(zone).date()

    def body(db: Session, log: JobLog) -> None:
        if not exchanges.is_trading_day(mic, local_day):
            log.info(f"{mic} is closed on {local_day.isoformat()}; no prices requested.")
            return
        prices = PriceService(db, ctx.chain_for(db), ctx.now())
        stored = 0
        for listing, instrument in tracked_listings(db, mic):
            try:
                summary = prices.update_latest(listing_ref(listing, instrument.isin), local_day)
                stored += summary.stored
                db.commit()
                log.info(
                    f"{listing.ticker}: {summary.stored} new or changed closes ({summary.source})"
                )
            except ProviderError as exc:
                db.rollback()
                log.error(f"{listing.ticker}: {exc}")
        if stored:
            publish_event(db, PRICE_UPDATE, {"mic": mic})

    return run_job(ctx, "eod", body, {"mic": mic, "day": local_day.isoformat()})


def fx_job(ctx: JobContext) -> JobResult:
    """Fetch ECB reference rates for every currency in use, and the ECB deposit facility rate
    (the default risk-free rate)."""

    def body(db: Session, log: JobLog) -> None:
        today = ctx.today()
        floor = first_transaction_date(db) or today - timedelta(days=365 * FX_FLOOR_YEARS)
        currencies = needed_currencies(db)
        if currencies:
            changed = FxService(db, ctx.ecb_for(db)).catch_up(currencies, today, floor)
            log.info(f"ECB rates for {', '.join(sorted(currencies))}: {changed} new or changed")
        else:
            log.info("No foreign currency in use; no exchange rates to fetch.")
        db.commit()
        try:
            changed = MacroService(db).update_deposit_rate(ctx.ecb_for(db), today, floor)
            log.info(f"ECB deposit facility rate: {changed} new or changed")
        except ProviderError as exc:
            log.error(f"ECB deposit facility rate: {exc}")

    return run_job(ctx, "fx", body)


def gap_job(ctx: JobContext, days: int = GAP_WINDOW_DAYS) -> JobResult:
    """Find trading days without a close in the recent past and refetch them (FR-MD-04)."""

    def body(db: Session, log: JobLog) -> None:
        today = ctx.today()
        prices = PriceService(db, ctx.chain_for(db), ctx.now())
        for listing, instrument in tracked_listings(db):
            ref = listing_ref(listing, instrument.isin)
            start = today - timedelta(days=days)
            gaps = prices.detect_gaps(ref, start)
            if not gaps:
                continue
            try:
                remaining = prices.fill_gaps(ref, start)
                db.commit()
                log.info(f"{listing.ticker}: {len(gaps)} gaps, {len(remaining)} left after refetch")
            except ProviderError as exc:
                db.rollback()
                log.error(f"{listing.ticker}: {exc}")

    return run_job(ctx, "gaps", body, {"days": days})


def refresh_job(ctx: JobContext) -> JobResult:
    """ "Refresh prices now": the newest closes for everything tracked, the quotes of what trades
    right now, then the ECB rates."""

    def body(db: Session, log: JobLog) -> None:
        today = ctx.today()
        prices = PriceService(db, ctx.chain_for(db), ctx.now())
        tracked = tracked_listings(db)
        if not tracked:
            log.info("Nothing is tracked yet.")
        stored = 0
        for listing, instrument in tracked:
            try:
                summary = prices.update_latest(listing_ref(listing, instrument.isin), today)
                stored += summary.stored
                db.commit()
                log.info(
                    f"{listing.ticker}: {summary.stored} new or changed closes ({summary.source})"
                )
            except ProviderError as exc:
                db.rollback()
                log.error(f"{listing.ticker}: {exc}")
        if stored:
            publish_event(db, PRICE_UPDATE, {"source": "refresh"})
        db.commit()
        try:  # the latest price of what trades right now, so it is there at once
            fetch_quotes(ctx, db, log)
        except ProviderError as exc:
            db.rollback()
            log.error(f"Quotes: {exc}")
        currencies = needed_currencies(db)
        if currencies:
            floor = first_transaction_date(db) or today - timedelta(days=365 * FX_FLOOR_YEARS)
            try:
                changed = FxService(db, ctx.ecb_for(db)).catch_up(currencies, today, floor)
                log.info(f"ECB rates for {', '.join(sorted(currencies))}: {changed} new or changed")
            except ProviderError as exc:
                log.error(f"ECB rates: {exc}")

    return run_job(ctx, "refresh", body)


QUOTE_RETENTION_FLOOR_DAYS = 1


def fetch_quotes(ctx: JobContext, db: Session, log: JobLog) -> None:
    """The delayed quotes of what is held or watched on a market that is open now, within the
    call budget (FR-MD-05)."""
    now = ctx.now()
    listings = open_now(held_listings(db), now)
    if not listings:
        log.info("No held listing is on an open market.")
        return
    reserve = len(tracked_listings(db)) + EOD_MARGIN
    service = QuoteService(db, ctx.chain_for(db), ctx.usage)
    summary = service.refresh(listing_refs(listings), now, reserve)
    if summary.source is None:
        why = "; ".join(f"{p}: {r}" for p, r in summary.skipped.items())
        log.info(f"No quotes fetched ({why or 'no provider is enabled'}).")
        return
    log.info(f"{summary.stored} new quote(s) for {len(listings)} listing(s) ({summary.source})")
    if summary.missing:  # not an error: a wrong symbol must not mark every run as failed
        log.info(f"No quote for {', '.join(summary.missing)} ({summary.source} does not know it).")
    if summary.stored:
        publish_event(db, PRICE_UPDATE, {"source": "quotes"})
    for provider, reason in summary.skipped.items():
        log.info(f"{provider} not used: {reason}")


def quotes_job(ctx: JobContext, only_if_open: bool = False) -> JobResult:
    """Delayed quotes for held listings on exchanges that are open now (FR-MD-05), within the
    call budget and never at the expense of the nightly closes. The scheduler passes
    `only_if_open`, so a quarter of an hour with every market closed leaves no run record."""
    if only_if_open:
        with ctx.session_factory() as db:
            if not open_now(held_listings(db), ctx.now()):
                return JobResult(0, "quotes", "skipped", "No held listing is on an open market.")

    def body(db: Session, log: JobLog) -> None:
        fetch_quotes(ctx, db, log)

    return run_job(ctx, "quotes", body)


def retention_job(ctx: JobContext) -> JobResult:
    """Prune what has a retention period (FR-SY-09): old quotes, and the live-update events
    that the browser has long since read."""

    def body(db: Session, log: JobLog) -> None:
        keep = load_section(db, "retention")
        quotes = prune_quotes(db, ctx.now(), int(keep.quotes_days))  # type: ignore[attr-defined]
        events = prune_events(db, ctx.now())
        log.info(f"Pruned {quotes} old quote(s) and {events} old event(s).")

    return run_job(ctx, "retention", body)


def actions_job(ctx: JobContext) -> JobResult:
    """Look for splits and dividends on everything held, and propose them (FR-MD-07)."""

    def body(db: Session, log: JobLog) -> None:
        proposals = propose_all(db, ctx.chain_for(db), ctx.today())
        log.info(
            f"{proposals.splits} split(s) and {proposals.dividends} dividend draft(s) proposed"
        )
        for note in proposals.notes:
            log.error(note)

    return run_job(ctx, "actions", body)


def backfill_job(ctx: JobContext, listing_id: int) -> JobResult:
    """History for a new listing: back to its first transaction, or a year if it has none
    (FR-MD-03). Runs when an instrument is added."""

    def body(db: Session, log: JobLog) -> None:
        listing = db.get(Listing, listing_id)
        if listing is None:
            log.error(f"Listing {listing_id} no longer exists.")
            return
        instrument = db.get(Instrument, listing.instrument_id)
        if instrument is None:
            log.error(f"Instrument {listing.instrument_id} no longer exists.")
            return
        today = ctx.today()
        first = first_transaction_date(db, instrument.id)
        start = (
            first - timedelta(days=BACKFILL_LEAD_DAYS)
            if first
            else today - timedelta(days=BACKFILL_DEFAULT_DAYS)
        )
        prices = PriceService(db, ctx.chain_for(db), ctx.now())
        summary = prices.backfill(listing_ref(listing, instrument.isin), start, today)
        log.info(
            f"{listing.ticker}: {summary.stored} closes from {start.isoformat()} ({summary.source})"
        )
        if summary.stored:
            publish_event(db, PRICE_UPDATE, {"listing_id": listing_id})

    return run_job(ctx, "backfill", body, {"listing_id": listing_id})


def describe_next_runs(now: datetime) -> dict[str, datetime]:
    """Next EOD fetch per known exchange (used by the System page and the scheduler)."""
    return {mic: exchanges.next_eod_job_time(mic, now) for mic in exchanges.EXCHANGES}
