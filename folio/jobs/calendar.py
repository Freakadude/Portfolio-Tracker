"""The event calendar jobs (FR-NW-09).

`calendar_job` writes the ready-made central bank dates and, when switched on, asks EODHD for the
earnings dates of directly held equities. `event_briefs_job` runs through the evening: an event
dated tomorrow gets an agent brief, or a plain reminder when the agent is off, has no key, has
used its budget or fails, so the day-before notice never depends on the model.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from folio.agent import budget
from folio.agent.run import run_agent
from folio.db.models_insight import CalendarEvent
from folio.db.models_ledger import Instrument
from folio.jobs.context import JobContext
from folio.jobs.runner import JobLog, JobResult, run_job
from folio.marketdata.base import ProviderError
from folio.marketdata.eodhd import EARNINGS_WEIGHT
from folio.marketdata.prices import tracked_listings
from folio.marketdata.quotes import EOD_MARGIN, listing_refs
from folio.news.calendar import (
    due_for_brief,
    parse_earnings,
    sync_shipped,
    upsert_earnings,
)
from folio.notify.service import notify
from folio.settings_schema import CalendarSettings
from folio.settings_store import load_section

BRIEF_FROM_HOUR = 18  # local time: the brief for tomorrow's event goes out from this hour
FOCUS_LIMIT = 300


def calendar_settings(db: Session) -> CalendarSettings:
    return CalendarSettings.model_validate(load_section(db, "calendar").model_dump())


def _equities(db: Session) -> dict[str, Instrument]:
    """EODHD symbol -> instrument, for directly held equities it prices."""
    equities = [(lst, i) for lst, i in tracked_listings(db) if i.asset_class == "EQUITY"]
    out: dict[str, Instrument] = {}
    for (_, instrument), ref in zip(equities, listing_refs(equities), strict=True):
        symbol = ref.provider_symbols.get("eodhd")
        if symbol:
            out[str(symbol)] = instrument
    return out


def calendar_job(ctx: JobContext) -> JobResult:
    def body(db: Session, log: JobLog) -> None:
        added = sync_shipped(db)
        db.commit()
        log.info(f"Ready-made central bank dates: {added} added.")
        if not calendar_settings(db).earnings_eodhd:
            log.info("Earnings dates from EODHD are switched off.")
            return
        provider = ctx.eodhd_for(db)
        if provider is None:
            log.info("Earnings dates: skipped, they need an EODHD API key (Settings, Providers).")
            return
        symbols = _equities(db)
        if not symbols:
            log.info("Earnings dates: no directly held equity is priced by EODHD.")
            return
        remaining = None if ctx.usage is None else ctx.usage.remaining("eodhd")
        reserve = len(tracked_listings(db)) + EOD_MARGIN  # the nightly closes come first
        if remaining is not None and remaining - EARNINGS_WEIGHT < reserve:
            log.info("Earnings dates: skipped, today's EODHD budget is kept for the closes.")
            return
        today = ctx.today()
        window = calendar_settings(db).earnings_days
        try:
            payload = provider.get_earnings(list(symbols), today, today + dt.timedelta(days=window))
        except ProviderError as exc:  # a plan without the calendar says so; nothing else stops
            log.error(f"Earnings dates: {exc}")
            return
        new, moved = upsert_earnings(db, parse_earnings(payload), symbols)
        db.commit()
        log.info(f"Earnings dates: {new} added, {moved} moved.")

    return run_job(ctx, "calendar", body)


def _focus(db: Session, event: CalendarEvent) -> str:
    name = None
    if event.instrument_id is not None:
        instrument = db.get(Instrument, event.instrument_id)
        name = None if instrument is None else instrument.name
    parts = [f"Tomorrow, {event.event_date.isoformat()}: {event.title}."]
    if name:
        parts.append(f"Instrument: {name}.")
    if event.detail:
        parts.append(event.detail)
    return " ".join(parts)[:FOCUS_LIMIT]


def _reminder(db: Session, event: CalendarEvent, now: dt.datetime) -> None:
    body = f"Tomorrow, {event.event_date.isoformat()}: {event.title}."
    if event.detail:
        body += f" {event.detail}."
    notify(
        db,
        source="digest",
        severity="info",
        subject=f"event:{event.id}",
        title=f"Tomorrow: {event.title}"[:200],
        body=body,
        push_title="Folio reminder",
        push_body=body[:300],
        push_body_anonymous="An event you follow is tomorrow.",
        link="/news?tab=calendar",
        now=now,
    )


def event_briefs_job(ctx: JobContext) -> JobResult:
    def body(db: Session, log: JobLog) -> None:
        now = ctx.now()
        local = now.astimezone(budget.timezone_of(db))
        if local.hour < BRIEF_FROM_HOUR:
            return
        events = due_for_brief(db, local.date() + dt.timedelta(days=1))
        if not events:
            return
        llm = ctx.llm_for(db)
        for event in events:
            briefed = False
            if llm is not None:
                outcome = run_agent(
                    db,
                    llm,
                    now,
                    run_type="event_brief",
                    trigger=f"event-brief:{event.id}",
                    focus=_focus(db, event),
                )
                briefed = outcome.status == "ok"
            if briefed:
                log.info(f"Brief for '{event.title}' made.")
            else:
                _reminder(db, event, now)
                log.info(f"Reminder for '{event.title}' sent (no brief could be made).")
            event.brief_sent_at = now
            db.commit()

    return run_job(ctx, "event_briefs", body)
