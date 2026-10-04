"""Market-data jobs: nightly closes per exchange, ECB rates, gap repair, instrument backfill."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from folio.db.models_ledger import Instrument, LedgerTransaction, Listing
from folio.jobs.context import JobContext
from folio.jobs.runner import JobLog, JobResult, run_job
from folio.marketdata import exchanges
from folio.marketdata.base import ProviderError
from folio.marketdata.corporate_actions import propose_all
from folio.marketdata.fx import FxService, needed_currencies
from folio.marketdata.prices import PriceService, listing_ref, tracked_listings

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


def eod_job(ctx: JobContext, mic: str, day: date | None = None) -> JobResult:
    """Fetch the latest closes for every tracked listing on one exchange. On a day the
    exchange is closed nothing is fetched (FR-MD-02)."""
    zone = ZoneInfo(str(exchanges.calendar(mic).tz))
    local_day = day or ctx.now().astimezone(zone).date()

    def body(db: Session, log: JobLog) -> None:
        if not exchanges.is_trading_day(mic, local_day):
            log.info(f"{mic} is closed on {local_day.isoformat()}; no prices requested.")
            return
        prices = PriceService(db, ctx.chain_for(db))
        for listing, instrument in tracked_listings(db, mic):
            try:
                summary = prices.update_latest(listing_ref(listing, instrument.isin), local_day)
                db.commit()
                log.info(
                    f"{listing.ticker}: {summary.stored} new or changed closes ({summary.source})"
                )
            except ProviderError as exc:
                db.rollback()
                log.error(f"{listing.ticker}: {exc}")

    return run_job(ctx, "eod", body, {"mic": mic, "day": local_day.isoformat()})


def fx_job(ctx: JobContext) -> JobResult:
    """Fetch ECB reference rates for every currency in use."""

    def body(db: Session, log: JobLog) -> None:
        currencies = needed_currencies(db)
        if not currencies:
            log.info("No foreign currency in use; nothing to fetch.")
            return
        today = ctx.today()
        floor = first_transaction_date(db) or today - timedelta(days=365 * FX_FLOOR_YEARS)
        changed = FxService(db, ctx.ecb_for(db)).catch_up(currencies, today, floor)
        log.info(f"ECB rates for {', '.join(sorted(currencies))}: {changed} new or changed")

    return run_job(ctx, "fx", body)


def gap_job(ctx: JobContext, days: int = GAP_WINDOW_DAYS) -> JobResult:
    """Find trading days without a close in the recent past and refetch them (FR-MD-04)."""

    def body(db: Session, log: JobLog) -> None:
        today = ctx.today()
        prices = PriceService(db, ctx.chain_for(db))
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
        prices = PriceService(db, ctx.chain_for(db))
        summary = prices.backfill(listing_ref(listing, instrument.isin), start, today)
        log.info(
            f"{listing.ticker}: {summary.stored} closes from {start.isoformat()} ({summary.source})"
        )

    return run_job(ctx, "backfill", body, {"listing_id": listing_id})


def describe_next_runs(now: datetime) -> dict[str, datetime]:
    """Next EOD fetch per known exchange (used by the System page and the scheduler)."""
    return {mic: exchanges.next_eod_job_time(mic, now) for mic in exchanges.EXCHANGES}
