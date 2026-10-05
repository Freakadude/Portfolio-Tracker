"""The event calendar (FR-NW-09): earnings dates, central bank meetings and the owner's own events.

Three sources feed one table. The ready-made central bank dates ship with Folio
(`data/central_bank_meetings.json`) and are written once; earnings dates of directly held
equities come from EODHD's earnings calendar when the owner has switched it on; the rest is typed
in. A row the owner deletes stays deleted, because the ready-made and EODHD rows are looked up
including deleted ones before anything is added.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.db.models_insight import CalendarEvent
from folio.db.models_ledger import Instrument

DATA = Path(__file__).parent / "data" / "central_bank_meetings.json"
KINDS = ("earnings", "central_bank", "custom")
MAX_DAYS = 180


class CalendarError(ValueError):
    """An event cannot be saved; the message is for the owner."""


@dataclass(frozen=True)
class Shipped:
    external_id: str
    kind: str
    day: date
    title: str


def load_shipped(path: Path = DATA) -> list[Shipped]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        Shipped(str(e["id"]), str(e["kind"]), date.fromisoformat(e["date"]), str(e["title"]))
        for e in raw["events"]
    ]


@dataclass(frozen=True)
class Earnings:
    code: str  # the provider's symbol, e.g. ASML.AS
    report_date: date
    period_end: date | None
    timing: str  # BeforeMarket | AfterMarket | ""
    estimate: Decimal | None


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def parse_earnings(payload: Any) -> list[Earnings]:
    """The rows of EODHD's earnings calendar (`{"earnings": [...]}`); rows without a report date
    are skipped."""
    rows = payload.get("earnings") if isinstance(payload, dict) else None
    out: list[Earnings] = []
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("code"):
            continue
        report = _day(row.get("report_date"))
        if report is None:
            continue
        estimate = row.get("estimate")
        out.append(
            Earnings(
                str(row["code"]),
                report,
                _day(row.get("date")),
                str(row.get("before_after_market") or ""),
                None if estimate in (None, "") else Decimal(str(estimate)),
            )
        )
    return out


def sync_shipped(db: Session, items: Sequence[Shipped] | None = None) -> int:
    """Write the ready-made dates that are not in the table yet, deleted ones included."""
    wanted = load_shipped() if items is None else items
    have = set(
        db.scalars(select(CalendarEvent.external_id).where(CalendarEvent.source == "shipped"))
    )
    added = 0
    for item in wanted:
        if item.external_id in have:
            continue
        db.add(
            CalendarEvent(
                kind=item.kind,
                event_date=item.day,
                title=item.title,
                source="shipped",
                external_id=item.external_id,
            )
        )
        added += 1
    return added


def upsert_earnings(
    db: Session, rows: Sequence[Earnings], instruments: Mapping[str, Instrument]
) -> tuple[int, int]:
    """Add new earnings dates and move ones the company has rescheduled. `instruments` maps the
    provider's symbol to the instrument. Returns (added, moved)."""
    added = moved = 0
    for row in rows:
        instrument = instruments.get(row.code)
        if instrument is None:
            continue
        external = f"{row.code}:{(row.period_end or row.report_date).isoformat()}"
        found = db.scalar(
            select(CalendarEvent).where(
                CalendarEvent.source == "eodhd", CalendarEvent.external_id == external
            )
        )
        timing = {"BeforeMarket": "before the market opens", "AfterMarket": "after the close"}.get(
            row.timing, ""
        )
        detail = ", ".join(
            p
            for p in (
                timing,
                "" if row.estimate is None else f"expected earnings per share {row.estimate}",
            )
            if p
        )
        if found is None:
            db.add(
                CalendarEvent(
                    kind="earnings",
                    event_date=row.report_date,
                    title=f"{instrument.name} reports earnings",
                    instrument_id=instrument.id,
                    source="eodhd",
                    external_id=external,
                    detail=detail,
                )
            )
            added += 1
        elif found.deleted_at is None and found.event_date != row.report_date:
            found.event_date, found.detail = row.report_date, detail
            found.brief_sent_at = None  # the brief belongs to the new day
            moved += 1
    return added, moved


# --- the owner's side ---------------------------------------------------------------------------


def _clean(title: str, day: date, kind: str) -> tuple[str, date, str]:
    text = " ".join(title.split())
    if not text:
        raise CalendarError("Give the event a title.")
    if len(text) > 200:
        raise CalendarError("The title can be at most 200 characters.")
    if kind not in KINDS:
        raise CalendarError(f"The kind must be one of {', '.join(KINDS)}.")
    return text, day, kind


def add_event(
    db: Session,
    *,
    title: str,
    day: date,
    kind: str = "custom",
    instrument_id: int | None = None,
    detail: str = "",
) -> CalendarEvent:
    text, day, kind = _clean(title, day, kind)
    if instrument_id is not None and db.get(Instrument, instrument_id) is None:
        raise CalendarError("That instrument does not exist.")
    event = CalendarEvent(
        kind=kind,
        event_date=day,
        title=text,
        instrument_id=instrument_id,
        source="owner",
        detail=detail.strip()[:2000],
    )
    db.add(event)
    db.flush()
    return event


def live(db: Session, event_id: int) -> CalendarEvent:
    event = db.get(CalendarEvent, event_id)
    if event is None or event.deleted_at is not None:
        raise CalendarError("That event does not exist.")
    return event


def upcoming(
    db: Session, today: date, days: int = 7, include_past_days: int = 0
) -> list[CalendarEvent]:
    """Events from `include_past_days` before today to `days` after, soonest first."""
    days = max(1, min(days, MAX_DAYS))
    return list(
        db.scalars(
            select(CalendarEvent)
            .where(
                CalendarEvent.deleted_at.is_(None),
                CalendarEvent.event_date >= today - timedelta(days=include_past_days),
                CalendarEvent.event_date <= today + timedelta(days=days),
            )
            .order_by(CalendarEvent.event_date, CalendarEvent.id)
        )
    )


def due_for_brief(db: Session, tomorrow: date) -> list[CalendarEvent]:
    """Events dated `tomorrow` that have not had their brief or reminder yet."""
    return list(
        db.scalars(
            select(CalendarEvent)
            .where(
                CalendarEvent.deleted_at.is_(None),
                CalendarEvent.event_date == tomorrow,
                CalendarEvent.brief_sent_at.is_(None),
            )
            .order_by(CalendarEvent.id)
        )
    )
