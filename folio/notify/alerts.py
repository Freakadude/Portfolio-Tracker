"""Price alerts (FR-INS-05): tell me when an instrument, held or watched, closes above or below a
price. An alert fires once when the close crosses its level and re-arms when the close is back
on the other side, so a price that stays above the level does not repeat itself.

The alert becomes a signal without a strategy; the notification service turns it into an inbox
item and the dispatcher pushes it (severity high: it is something the owner asked for).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.db.models_ledger import Instrument
from folio.db.models_strategy import PriceAlert, Signal
from folio.instruments import primary_listing
from folio.marketdata.prices import PriceService

SEVERITY = "high"


def crossed(condition: str, close: Decimal, threshold: Decimal) -> bool:
    return close > threshold if condition == "above" else close < threshold


def evaluate_alerts(
    db: Session, now: datetime, instrument_ids: Iterable[int] | None = None
) -> list[Signal]:
    """Check the active alerts (all, or only for these instruments) against the latest close
    in the trading currency. Returns the signals created."""
    query = select(PriceAlert).where(PriceAlert.active.is_(True), PriceAlert.deleted_at.is_(None))
    if instrument_ids is not None:
        query = query.where(PriceAlert.instrument_id.in_(set(instrument_ids)))
    prices = PriceService(db)
    created: list[Signal] = []
    for alert in db.scalars(query.order_by(PriceAlert.id)):
        instrument = db.get(Instrument, alert.instrument_id)
        listing = primary_listing(db, alert.instrument_id)
        bar = None if listing is None else prices.last_bar(listing.id)
        if instrument is None or listing is None or bar is None:
            continue
        if not crossed(alert.condition, bar.close, alert.threshold):
            alert.armed = True  # back on the other side: the next crossing fires again
            continue
        if not alert.armed:
            continue
        alert.armed, alert.last_fired_at = False, now
        level = f"{alert.threshold.normalize():f} {listing.currency}"
        title = f"{instrument.name} closed {alert.condition} {level}"
        note = f" Your note: {alert.note}" if alert.note else ""
        signal = Signal(
            strategy_version_id=None,
            rule_id=f"alert:{alert.id}",
            rule_type="price_alert",
            subject=instrument.name,
            ts=now,
            severity=SEVERITY,
            message=f"{title}: {bar.close.normalize():f} on {bar.date.isoformat()}.{note}",
            value=bar.close,
            payload={
                "title": title,
                "push": f"{instrument.name} closed {alert.condition} the level you set.",
                "push_anonymous": f"A watched instrument closed {alert.condition} a level you set.",
                "instrument_id": str(instrument.id),
                "alert_id": str(alert.id),
            },
            dedup_key=f"alert:{alert.id}:{bar.date.isoformat()}",
            state="new",
            shadow=False,
        )
        db.add(signal)
        created.append(signal)
    db.flush()
    return created
