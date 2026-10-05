"""The quarterly strategy review (FR-ST-08): the summary of a quarter, and a way to put it in the
inbox now."""

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.db.base import utcnow
from folio.strategies.review import Quarter, Review, gather, post, render

router = APIRouter(prefix="/strategy-review", tags=["strategies"])


class ReviewPointOut(BaseModel):
    day: date
    weight: Decimal
    drift_pp: Decimal


class ReviewSleeveOut(BaseModel):
    id: str
    target_pct: Decimal | None
    month_ends: list[ReviewPointOut]
    worst: ReviewPointOut | None
    days_outside_hard: int
    days_outside_soft: int


class ReviewSignalOut(BaseModel):
    rule_id: str
    count: int
    worst_severity: str


class ReviewRecommendationsOut(BaseModel):
    made: int
    by_status: dict[str, int]
    by_action: dict[str, int]


class StrategyReviewOut(BaseModel):
    quarter: str
    start: date
    end: date
    complete: bool  # the quarter is over
    strategy: str
    sleeves: list[ReviewSleeveOut]
    signals: list[ReviewSignalOut]
    recommendations: ReviewRecommendationsOut
    days_with_data: int
    notes: list[str]
    text: str


class ReviewPostedOut(BaseModel):
    quarter: str
    posted: bool  # False when the quarter already had its item


def _quarter(text: str | None, today: date) -> Quarter:
    try:
        return Quarter.parse(text) if text else Quarter.of(today).previous()
    except ValueError as exc:
        raise ApiError(422, "Unknown quarter", str(exc)) from exc


def _out(review: Review, today: date) -> StrategyReviewOut:
    q = review.quarter
    return StrategyReviewOut(
        quarter=q.label,
        start=q.start,
        end=q.end,
        complete=q.end < today,
        strategy=review.strategy,
        sleeves=[
            ReviewSleeveOut(
                id=s.id,
                target_pct=s.target_pct,
                month_ends=[ReviewPointOut(**vars(p)) for p in s.month_ends],
                worst=None if s.worst is None else ReviewPointOut(**vars(s.worst)),
                days_outside_hard=s.days_outside_hard,
                days_outside_soft=s.days_outside_soft,
            )
            for s in review.sleeves
        ],
        signals=[ReviewSignalOut(**vars(s)) for s in review.signals],
        recommendations=ReviewRecommendationsOut(
            made=review.recommendations.made,
            by_status=review.recommendations.by_status,
            by_action=review.recommendations.by_action,
        ),
        days_with_data=review.days_with_data,
        notes=review.notes,
        text=render(review),
    )


@router.get("", response_model=StrategyReviewOut)
def get_review(
    _user: UserDep,
    db: DbDep,
    quarter: Annotated[
        str | None, Query(description="like 2026Q3; default the last quarter")
    ] = None,
) -> StrategyReviewOut:
    """The summary of a quarter for the active strategy: drift by sleeve, signals fired and what
    became of the agent's advice. Written by code, not by a model."""
    today = utcnow().date()
    review = gather(db, _quarter(quarter, today), today)
    if review is None:
        raise ApiError(404, "No active strategy", "Make a strategy active to get a review.")
    return _out(review, today)


@router.post("/post", response_model=ReviewPostedOut)
def post_review(
    _user: UserDep,
    db: DbDep,
    quarter: Annotated[str | None, Query()] = None,
) -> ReviewPostedOut:
    """Put the review of a finished quarter in the inbox; a quarter gets one item only."""
    now = utcnow()
    wanted = _quarter(quarter, now.date())
    if wanted.end >= now.date():
        raise ApiError(409, "The quarter is not over", f"{wanted.label} ends on {wanted.end}.")
    review = gather(db, wanted, now.date())
    if review is None:
        raise ApiError(404, "No active strategy", "Make a strategy active to get a review.")
    item = post(db, review, now)
    return ReviewPostedOut(quarter=wanted.label, posted=item is not None)
