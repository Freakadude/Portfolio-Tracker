"""The monthly look-through job (FR-MD-09): refreshes the holdings of every ETF that has a
download address or EODHD switched on, and says so in the inbox when a snapshot has gone stale."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.db.models_insight import EtfSnapshot
from folio.db.models_ledger import Instrument
from folio.db.models_strategy import Notification
from folio.instruments import primary_listing
from folio.jobs.context import JobContext
from folio.jobs.runner import JobLog, JobResult, run_job
from folio.lookthrough.parse import HoldingsRead, read_holdings, suggest
from folio.lookthrough.service import HoldingsError, store_snapshot
from folio.lookthrough.sources import fetch_issuer_file, parse_eodhd_holdings
from folio.marketdata.base import ProviderError
from folio.marketdata.prices import listing_ref
from folio.notify.service import notify
from folio.settings_schema import LookThroughSettings
from folio.settings_store import load_section

NOTICE_EVERY = timedelta(days=30)


def _fetch(
    ctx: JobContext, db: Session, instrument: Instrument, url: str | None, eodhd: bool
) -> tuple[HoldingsRead | None, date | None, str]:
    """The holdings from the first source that works: the issuer's file, then EODHD. The third
    value is the source name, or what went wrong."""
    problems: list[str] = []
    if url:
        http = ctx.issuer_for(db)
        if http is None:
            problems.append("issuer downloads are not available")
        else:
            try:
                file = suggest(fetch_issuer_file(http, url))
                read = read_holdings(file)
                if not read.errors:
                    return read, file.as_of, "url"
                problems.append(read.errors[0])
            except (ProviderError, ValueError) as exc:
                problems.append(str(exc))
    if eodhd:
        provider = ctx.eodhd_for(db)
        listing = primary_listing(db, instrument.id)
        if provider is None or listing is None:
            problems.append("EODHD needs an API key (Settings, Providers)")
        else:
            try:
                read = parse_eodhd_holdings(
                    provider.get_fundamentals(listing_ref(listing, instrument.isin))
                )
                if not read.errors:
                    return read, None, "eodhd"
                problems.append(read.errors[0])
            except ProviderError as exc:
                problems.append(str(exc))
    return None, None, "; ".join(problems) or "no source is set up"


def lookthrough_job(ctx: JobContext, instrument_id: int | None = None) -> JobResult:
    def body(db: Session, log: JobLog) -> None:
        today = ctx.today()
        config = LookThroughSettings.model_validate(load_section(db, "lookthrough").model_dump())
        for key, source in config.sources.items():
            if instrument_id is not None and str(instrument_id) != key:
                continue
            if not source.url and not source.eodhd:
                continue
            instrument = db.get(Instrument, int(key))
            if instrument is None or instrument.deleted_at is not None:
                continue
            # fetch first and write after: a call charged to the budget uses another connection
            read, stated, how = _fetch(ctx, db, instrument, source.url, source.eodhd)
            if read is None:
                log.error(f"{instrument.name}: {how}")
                continue
            try:
                store_snapshot(db, instrument.id, read, stated or today, how, actor="worker")
            except HoldingsError as exc:
                log.error(f"{instrument.name}: {exc}")
                continue
            db.commit()
            log.info(f"{instrument.name}: {len(read.constituents)} holdings from {how}")
        _stale_notices(ctx, db, config.stale_days)

    return run_job(ctx, "lookthrough", body, {"instrument_id": instrument_id})


def _stale_notices(ctx: JobContext, db: Session, stale_days: int) -> None:
    """A low-severity item for each ETF whose newest snapshot is older than `stale_days`,
    at most once a month per ETF."""
    now, today = ctx.now(), ctx.today()
    newest: dict[int, EtfSnapshot] = {}
    for snap in db.scalars(select(EtfSnapshot).order_by(EtfSnapshot.as_of)):
        newest[snap.instrument_id] = snap
    for instrument_id, snap in newest.items():
        age = (today - snap.as_of).days
        instrument = db.get(Instrument, instrument_id)
        if age <= stale_days or instrument is None or instrument.deleted_at is not None:
            continue
        subject = f"holdings:{instrument_id}"
        recent = db.scalar(
            select(Notification.id).where(
                Notification.subject == subject, Notification.created_at >= now - NOTICE_EVERY
            )
        )
        if recent is not None:
            continue
        notify(
            db,
            source="system",
            severity="low",
            subject=subject,
            title=f"{instrument.name}: the holdings are {age} days old",
            body=(
                f"The latest look-through snapshot of {instrument.name} is from "
                f"{snap.as_of.isoformat()}. Upload a fresh holdings file on its position page, "
                "or set a download address so Folio refreshes it monthly."
            ),
            push_body=f"{instrument.name}: holdings are {age} days old.",
            push_body_anonymous="Folio has a new item.",
            link=f"/holdings/{instrument_id}",
            now=now,
        )
    db.commit()
