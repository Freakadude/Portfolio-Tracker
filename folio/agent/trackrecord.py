"""Measures the agent's past recommendations against later prices and reports the track record
(FR-AG-06). The arithmetic is in `outcomes`; this module finds the instruments and the closes."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.agent import outcomes
from folio.db.models_insight import Recommendation
from folio.db.models_ledger import Instrument, PriceBar
from folio.instruments import primary_listing

HISTORY_DAYS = (
    max(outcomes.HORIZONS) + outcomes.GRACE_DAYS + 7
)  # a week of margin if the worker was down


def instrument_for(db: Session, subject: str) -> Instrument | None:
    """The instrument a recommendation's subject names (its name, ISIN or id), if any."""
    return db.scalar(
        select(Instrument).where(
            (Instrument.name == subject)
            | (Instrument.isin == subject)
            | (Instrument.id == int(subject) if subject.isdigit() else False)  # noqa: SIM300
        )
    )


def latest_close(db: Session, instrument: Instrument) -> Decimal | None:
    listing = primary_listing(db, instrument.id)
    if listing is None:
        return None
    bar = db.scalars(
        select(PriceBar).where(PriceBar.listing_id == listing.id).order_by(PriceBar.date.desc())
    ).first()
    return None if bar is None else bar.close


def close_near(db: Session, instrument: Instrument, day: dt.date) -> Decimal | None:
    """The close on `day`, or the last one in the few days before it."""
    listing = primary_listing(db, instrument.id)
    if listing is None:
        return None
    bar = db.scalars(
        select(PriceBar)
        .where(
            PriceBar.listing_id == listing.id,
            PriceBar.date <= day,
            PriceBar.date >= day - dt.timedelta(days=outcomes.LOOKBACK_DAYS),
        )
        .order_by(PriceBar.date.desc())
    ).first()
    return None if bar is None else bar.close


def measure_due(db: Session, today: dt.date) -> int:
    """Fill in the outcome of every recommendation whose +7, +30 or +90 day mark has passed.
    A horizon whose price is not there yet waits; one that is long past with no price is closed
    as "no price". Returns how many horizons were written."""
    since = dt.datetime.combine(today - dt.timedelta(days=HISTORY_DAYS), dt.time.min, dt.UTC)
    written = 0
    rows = db.scalars(
        select(Recommendation).where(
            Recommendation.status != "refused", Recommendation.created_at >= since
        )
    )
    for rec in rows:
        starts = {
            subject: Decimal(str(close)) for subject, close in (rec.price_at_creation or {}).items()
        }
        created = rec.created_at.date()
        outcome = dict(rec.outcome or {})
        todo = outcomes.pending(created, today, outcome)
        if not starts:
            for days in todo:  # nothing to compare: say so once, at the first horizon
                outcome[outcomes.key(days)] = outcomes.measure(
                    rec.action_type, {}, {}, outcomes.horizon_date(created, days)
                )
                written += 1
            if todo:
                rec.outcome = outcome
            continue
        for days in todo:
            at = outcomes.horizon_date(created, days)
            ends: dict[str, Decimal | None] = {}
            for subject in starts:
                instrument = instrument_for(db, subject)
                ends[subject] = None if instrument is None else close_near(db, instrument, at)
            complete = all(ends[s] is not None for s in starts)
            if complete or outcomes.horizon_due_for_giving_up(created, today, days):
                outcome[outcomes.key(days)] = outcomes.measure(rec.action_type, starts, ends, at)
                written += 1
        if len(outcome) != len(rec.outcome or {}):
            rec.outcome = outcome
    db.flush()
    return written


def track_record(db: Session, decision_horizon: int = 30) -> outcomes.TrackRecord:
    rows = [
        outcomes.Row(r.action_type, r.status, r.outcome or {})
        for r in db.scalars(select(Recommendation).where(Recommendation.status != "refused"))
    ]
    return outcomes.summarise(rows, decision_horizon)
