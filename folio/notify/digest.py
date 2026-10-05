"""Daily and weekly digests (FR-NT-06): how the portfolio moved, the open items, and what is
coming up. Built from the numbers alone; the agent's daily review (Phase 4) will add to it.
The push says only that the digest is ready and how many items wait, never an amount."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio import analytics_service as svc
from folio.db.models_strategy import Notification
from folio.notify.service import notify
from folio.strategies import service as strategies
from folio.strategies.rules import next_contribution
from folio.strategies.schema import SEVERITIES

UPCOMING_DAYS = 7
TOP_ITEMS = 5


def _money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):,.2f} EUR"


def _change_line(db: Session, today: date, days: int) -> str | None:
    ctx = svc.get_context(db, today)
    if ctx.empty:
        return None
    now = ctx.points[ctx.index(today)]
    then = ctx.points[ctx.index(today - timedelta(days=days))]
    result = now.total_pnl_eur - then.total_pnl_eur  # what the markets did, not deposits
    sign = "+" if result >= 0 else "-"
    period = "today" if days == 1 else f"over {days} days"
    return f"Value {_money(now.value_eur)}; result {period} {sign}{_money(abs(result))}."


def _upcoming(db: Session, today: date) -> list[str]:
    found = strategies.managing_strategy(db)
    if found is None:
        return []
    definition = strategies.active_definition(db, found)
    since = strategies.latest(db, found).created_at.date()
    horizon = today + timedelta(days=UPCOMING_DAYS)
    out = []
    plan = definition.contribution_plan
    if plan is not None and plan.amount_eur is not None:
        due = next_contribution(plan.next_date, plan.cadence, today)
        if due is not None and due <= horizon:
            out.append(f"Contribution due {due.isoformat()}")
    for t in definition.theses:
        due_review = t.next_review
        if due_review is None and t.review_every_days:
            due_review = since + timedelta(days=t.review_every_days)
            while due_review < today:
                due_review += timedelta(days=t.review_every_days)
        if due_review is not None and today <= due_review <= horizon:
            out.append(f"Thesis review for {t.sleeve or t.instrument} on {due_review.isoformat()}")
    return out


def build_digest(db: Session, kind: str, now: datetime, today: date) -> Notification:
    days = 1 if kind == "daily" else 7
    since = now - timedelta(days=days)
    items = [
        n
        for n in db.scalars(
            select(Notification).where(
                Notification.created_at >= since,
                Notification.read_at.is_(None),
                Notification.source != "digest",
            )
        )
    ]
    items.sort(key=lambda n: (-SEVERITIES.index(n.severity), n.created_at))
    upcoming = _upcoming(db, today)
    lines = []
    change = _change_line(db, today, days)
    if change:
        lines.append(change)
    if items:
        lines.append(f"{len(items)} open item{'s' if len(items) != 1 else ''}:")
        lines += [f"- [{n.severity}] {n.title}" for n in items[:TOP_ITEMS]]
    else:
        lines.append("Nothing waiting for you.")
    if upcoming:
        lines.append("Coming up:")
        lines += [f"- {u}" for u in upcoming]
    label = "Daily summary" if kind == "daily" else "Weekly summary"
    count = len(items)
    push = f"Your {label.lower()} is ready: {count} open item{'s' if count != 1 else ''}"
    push += f", {len(upcoming)} coming up." if upcoming else "."
    return notify(
        db,
        source="digest",
        severity="info",
        subject=f"{kind} digest",
        title=f"{label}, {today.isoformat()}",
        body="\n".join(lines),
        push_title=f"Folio {label.lower()}",
        push_body=push,
        push_body_anonymous=push,
        link="/insights",
        now=now,
    )
