"""The owner's side of the agent's recommendations (FR-AG-05): the open list, the details, and
accept, reject, snooze."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select

from folio.agent import lifecycle
from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.db.base import utcnow
from folio.db.models_insight import Calculation, Recommendation

router = APIRouter(prefix="/recommendations", tags=["recommendations"])
AI_LABEL = "AI-generated, not financial advice."


class RecEvidenceOut(BaseModel):
    kind: str
    ref: str
    note: str


class RecOrderOut(BaseModel):
    side: str
    sleeve: str
    instrument_id: int
    name: str
    quantity: Decimal
    price: Decimal
    currency: str | None
    amount_eur: Decimal


class RecommendationOut(BaseModel):
    id: int
    run_id: int
    created_at: datetime
    action_type: str
    severity: str
    subjects: list[str]
    title: str
    summary: str
    rationale: str
    calculation_id: int | None
    evidence: list[RecEvidenceOut]
    sources: list[str]
    confidence: str
    departs_from_principles: str | None  # when set, the item gets the "departs" badge
    what_would_change_this: str
    expires_at: datetime
    status: str  # new | seen | accepted | rejected | snoozed | expired
    user_note: str | None
    snoozed_until: datetime | None
    linked_transaction_ids: list[int]
    ai_label: str = AI_LABEL


class RecommendationDetailOut(RecommendationOut):
    orders: list[RecOrderOut]  # the calculation's orders, for "Copy to drafts" and the What-if
    remainder_eur: Decimal | None
    plan_current: bool | None  # null without a calculation


class DecisionIn(BaseModel):
    action: Literal["seen", "accept", "reject", "snooze"]
    note: str | None = Field(default=None, max_length=1000)  # the one-line reason for a rejection
    days: int | None = None  # for snooze
    create_drafts: bool = False  # on accept: draft transactions from the calculation


class DecisionOut(BaseModel):
    recommendation: RecommendationDetailOut
    drafts: list[int]  # ids of the draft transactions made, to confirm on Insights


def _out(rec: Recommendation, now: datetime) -> dict[str, Any]:
    status = "expired" if rec.status in lifecycle.LIVE and rec.expires_at <= now else rec.status
    return {
        "id": rec.id,
        "run_id": rec.run_id,
        "created_at": rec.created_at,
        "action_type": rec.action_type,
        "severity": rec.severity,
        "subjects": list(rec.subjects or []),
        "title": rec.title,
        "summary": rec.summary,
        "rationale": rec.rationale,
        "calculation_id": rec.calculation_id,
        "evidence": [RecEvidenceOut(**e) for e in (rec.evidence or [])],
        "sources": list(rec.sources or []),
        "confidence": rec.confidence,
        "departs_from_principles": rec.departs_from_principles,
        "what_would_change_this": rec.what_would_change_this,
        "expires_at": rec.expires_at,
        "status": status,
        "user_note": rec.user_note,
        "snoozed_until": rec.snoozed_until,
        "linked_transaction_ids": list(rec.linked_transaction_ids or []),
    }


def _detail(db: DbDep, rec: Recommendation, now: datetime) -> RecommendationDetailOut:
    calc = db.get(Calculation, rec.calculation_id) if rec.calculation_id else None
    orders: list[RecOrderOut] = []
    remainder: Decimal | None = None
    current: bool | None = None
    if calc is not None:
        plan = calc.plan or {}
        for o in plan.get("orders", []):
            price_eur, quantity = Decimal(str(o["price_eur"])), Decimal(str(o["quantity"]))
            orders.append(
                RecOrderOut(
                    side=o["side"],
                    sleeve=o["sleeve"],
                    instrument_id=int(o["instrument_id"]),
                    name=o["name"],
                    quantity=quantity,
                    price=Decimal(str(o["price"])),
                    currency=o.get("currency"),
                    amount_eur=quantity * price_eur,
                )
            )
        remainder = Decimal(str(plan.get("remainder_eur", "0")))
        current = (
            lifecycle.plan_is_current(db, calc, now.date())
            if rec.status in lifecycle.LIVE
            else None
        )
    return RecommendationDetailOut(
        **_out(rec, now), orders=orders, remainder_eur=remainder, plan_current=current
    )


@router.get("", response_model=list[RecommendationOut])
def list_recommendations(
    _user: UserDep,
    db: DbDep,
    status: Annotated[
        str, Query(pattern="^(open|all|new|seen|accepted|rejected|snoozed|expired)$")
    ] = "open",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[RecommendationOut]:
    """Recommendations, newest first. `open` is what needs a decision: new or seen, and not past
    its expiry. Items the code gate refused are not advice and are listed only in the run trace."""
    now = utcnow()
    query = select(Recommendation).where(Recommendation.status != "refused")
    if status == "open":
        query = query.where(
            Recommendation.status.in_(lifecycle.OPEN), Recommendation.expires_at > now
        )
    elif status == "expired":
        query = query.where(
            or_(
                Recommendation.status == "expired",
                and_(Recommendation.status.in_(lifecycle.LIVE), Recommendation.expires_at <= now),
            )
        )
    elif status != "all":
        query = (
            query.where(Recommendation.status == status, Recommendation.expires_at > now)
            if status in lifecycle.LIVE
            else query.where(Recommendation.status == status)
        )
    rows = db.scalars(query.order_by(Recommendation.id.desc()).limit(limit))
    return [RecommendationOut(**_out(r, now)) for r in rows]


@router.get("/{rec_id}", response_model=RecommendationDetailOut)
def one_recommendation(rec_id: int, _user: UserDep, db: DbDep) -> RecommendationDetailOut:
    rec = db.get(Recommendation, rec_id)
    if rec is None or rec.status == "refused":
        raise ApiError(404, "Not found", "That recommendation does not exist.")
    return _detail(db, rec, utcnow())


@router.patch("/{rec_id}", response_model=DecisionOut)
def decide(rec_id: int, body: DecisionIn, _user: UserDep, db: DbDep) -> DecisionOut:
    """Mark it seen, accept it (optionally as draft transactions), reject it with a reason, or
    snooze it for a number of days."""
    now = utcnow()
    try:
        rec, drafts = lifecycle.decide(
            db,
            rec_id,
            body.action,
            now,
            note=body.note,
            days=body.days,
            create_drafts=body.create_drafts,
        )
    except lifecycle.LifecycleError as exc:
        missing = "does not exist" in str(exc)
        status = 404 if missing else 409 if exc.conflict else 422
        raise ApiError(status, "Cannot record the decision", str(exc)) from exc
    return DecisionOut(recommendation=_detail(db, rec, now), drafts=[d.id for d in drafts])
