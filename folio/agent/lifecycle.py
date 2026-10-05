"""The life of a recommendation (FR-AG-05): new, seen, then accepted, rejected, snoozed or expired.

Accepting can turn the calculation behind the advice into draft transactions that the owner then
confirms one by one on Insights; that is only done while the calculation still holds, that is,
while running it again today gives the same orders. Rejecting takes an optional one-line reason,
which later runs see through `get_recommendation_history`. Snoozing hides an item for a number of
days. Items past their expiry leave the open list by themselves. Every decision is audited
(FR-SY-08) and announced on the live-update stream.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.audit import write_audit
from folio.db.models_insight import Calculation, Recommendation
from folio.db.models_ledger import LedgerTransaction
from folio.db.models_strategy import StrategyVersion
from folio.events import RECOMMENDATION, publish_event
from folio.ledger_service import TransactionError
from folio.strategies.planning import DraftOrder, calculate, to_drafts
from folio.strategies.schema import StrategyDef

OPEN = ("new", "seen")
LIVE = ("new", "seen", "snoozed")
ACTIONS = ("seen", "accept", "reject", "snooze")
NOTE_LIMIT = 300
MAX_SNOOZE_DAYS = 30


class LifecycleError(ValueError):
    """The decision cannot be made; the message is for the owner. `conflict` marks a state
    problem (409) rather than a bad request (422)."""

    def __init__(self, message: str, conflict: bool = False) -> None:
        super().__init__(message)
        self.conflict = conflict


def is_open(rec: Recommendation, now: dt.datetime) -> bool:
    return rec.status in OPEN and rec.expires_at > now


def _announce(db: Session, rec: Recommendation, what: str) -> None:
    publish_event(db, RECOMMENDATION, {"id": rec.id, "status": rec.status, "what": what})


def expire_due(db: Session, now: dt.datetime) -> tuple[int, int]:
    """Items past their expiry become `expired`; snoozed items whose time is up come back as
    new. Returns how many of each."""
    expired = woken = 0
    for rec in db.scalars(select(Recommendation).where(Recommendation.status.in_(LIVE))):
        if rec.expires_at <= now:
            rec.status = "expired"
            write_audit(db, "worker", "recommendation", "expire", entity_id=rec.id,
                        diff={"status": {"old": "live", "new": "expired"}})  # fmt: skip
            _announce(db, rec, "expired")
            expired += 1
        elif rec.status == "snoozed" and rec.snoozed_until is not None and rec.snoozed_until <= now:
            rec.status, rec.snoozed_until = "new", None
            _announce(db, rec, "woken")
            woken += 1
    db.flush()
    return expired, woken


def plan_is_current(db: Session, calc: Calculation, today: dt.date) -> bool:
    """Whether running the same calculation again gives the same orders."""
    version = (
        db.get(StrategyVersion, calc.strategy_version_id) if calc.strategy_version_id else None
    )
    if version is None:
        return False
    inputs = calc.inputs or {}
    raw = inputs.get("amount_eur")
    amount = None if raw in (None, "") else Decimal(str(raw))
    try:
        result = calculate(
            db,
            StrategyDef.model_validate(version.definition),
            cast("Any", calc.kind),
            today,
            amount,
            cast("str | None", inputs.get("sleeve") or None),
        )
    except (TransactionError, ValueError):
        return False

    def key(side: str, instrument_id: int, quantity: str) -> tuple[str, int, Decimal]:
        return side, instrument_id, Decimal(quantity)

    now_orders = sorted(key(o.side, o.instrument_id, str(o.quantity)) for o in result.plan.orders)
    then = sorted(
        key(o["side"], int(o["instrument_id"]), str(o["quantity"]))
        for o in (calc.plan or {}).get("orders", [])
    )
    return now_orders == then


def _drafts(db: Session, rec: Recommendation, today: dt.date) -> list[LedgerTransaction]:
    calc = db.get(Calculation, rec.calculation_id) if rec.calculation_id else None
    if calc is None or not (calc.plan or {}).get("orders"):
        raise LifecycleError("This advice has no order list to turn into draft transactions.")
    if not plan_is_current(db, calc, today):
        raise LifecycleError(
            "The portfolio or the prices have changed since this advice was made, so its order "
            "list is out of date. Ask for a new review before making drafts.",
            conflict=True,
        )
    orders = [
        DraftOrder(
            o["side"],
            int(o["instrument_id"]),
            Decimal(str(o["quantity"])),
            Decimal(str(o["price"])),
            o.get("account_id"),
        )
        for o in calc.plan["orders"]
    ]
    return to_drafts(db, orders, today, note=f"From recommendation {rec.id}: {rec.title}"[:200])


def decide(
    db: Session,
    rec_id: int,
    action: str,
    now: dt.datetime,
    *,
    note: str | None = None,
    days: int | None = None,
    create_drafts: bool = False,
    actor: str = "user",
) -> tuple[Recommendation, list[LedgerTransaction]]:
    rec = db.get(Recommendation, rec_id)
    if rec is None or rec.status == "refused":
        raise LifecycleError("That recommendation does not exist.")
    if action not in ACTIONS:
        raise LifecycleError("The action must be seen, accept, reject or snooze.")
    if rec.status not in LIVE or rec.expires_at <= now:
        raise LifecycleError(
            f"This recommendation is {rec.status} and can no longer be changed.", conflict=True
        )
    before = rec.status
    drafts: list[LedgerTransaction] = []
    cleaned = " ".join((note or "").split())[:NOTE_LIMIT] or None
    if action == "seen":
        if rec.status == "new":
            rec.status = "seen"
    elif action == "accept":
        if create_drafts:
            drafts = _drafts(db, rec, now.date())
            rec.linked_transaction_ids = [d.id for d in drafts]
        rec.status, rec.user_note = "accepted", cleaned
    elif action == "reject":
        rec.status, rec.user_note = "rejected", cleaned
    else:
        if days is None or not 1 <= days <= MAX_SNOOZE_DAYS:
            raise LifecycleError(f"Snooze for 1 to {MAX_SNOOZE_DAYS} days.")
        rec.status, rec.snoozed_until = "snoozed", now + dt.timedelta(days=days)
    if rec.status != before or action != "seen":
        write_audit(
            db, actor, "recommendation", action, entity_id=rec.id,
            diff={"status": {"old": before, "new": rec.status}, "note": cleaned,
                  "transactions": [d.id for d in drafts]},
        )  # fmt: skip
    _announce(db, rec, action)
    db.flush()
    return rec, drafts
