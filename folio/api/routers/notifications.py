"""The inbox and the phone channels (FR-NT-01, FR-NT-02, FR-NT-08)."""

import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from folio.api.deps import DbDep, StoreDep, UserDep
from folio.api.errors import ApiError
from folio.db.base import utcnow
from folio.db.models_strategy import Notification, NotificationDelivery
from folio.notify.channels import CHANNELS, ChannelError, PushMessage
from folio.notify.service import build_channels, notification_settings

router = APIRouter(prefix="/notifications", tags=["notifications"])


class DeliveryOut(BaseModel):
    id: int
    notification_id: int
    channel: str
    status: str
    attempts: int
    last_error: str | None
    sent_at: dt.datetime | None
    next_attempt_at: dt.datetime | None
    merged_into_id: int | None


class NotificationOut(BaseModel):
    id: int
    source: str
    subject: str
    severity: str
    title: str
    body: str
    link: str | None
    created_at: dt.datetime
    read_at: dt.datetime | None
    deliveries: list[DeliveryOut]


class InboxOut(BaseModel):
    items: list[NotificationOut]
    total: int
    unread: int


class CountOut(BaseModel):
    unread: int


class ReadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[int] = Field(default_factory=list, max_length=1000)
    all: bool = False  # every unread item
    read: bool = True  # false marks them unread again


class TestOut(BaseModel):
    ok: bool
    error: str | None


def _delivery(d: NotificationDelivery) -> DeliveryOut:
    return DeliveryOut(
        id=d.id,
        notification_id=d.notification_id,
        channel=d.channel,
        status=d.status,
        attempts=d.attempts,
        last_error=d.last_error,
        sent_at=d.sent_at,
        next_attempt_at=d.next_attempt_at,
        merged_into_id=d.merged_into_id,
    )


def _unread(db: Session) -> int:
    return db.scalar(select(func.count()).where(Notification.read_at.is_(None))) or 0


@router.get("", response_model=InboxOut)
def inbox(
    _user: UserDep,
    db: DbDep,
    severity: str | None = None,
    source: str | None = None,
    status: Literal["unread", "read", "all"] = "all",
    subject: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InboxOut:
    """Newest first, filtered by type (source), severity, read state and subject."""
    query = select(Notification)
    if severity:
        query = query.where(Notification.severity.in_(severity.split(",")))
    if source:
        query = query.where(Notification.source.in_(source.split(",")))
    if status == "unread":
        query = query.where(Notification.read_at.is_(None))
    elif status == "read":
        query = query.where(Notification.read_at.is_not(None))
    if subject:
        query = query.where(Notification.subject.ilike(f"%{subject}%"))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = list(
        db.scalars(
            query.order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    deliveries: dict[int, list[DeliveryOut]] = {n.id: [] for n in rows}
    if rows:
        for d in db.scalars(
            select(NotificationDelivery)
            .where(NotificationDelivery.notification_id.in_(deliveries))
            .order_by(NotificationDelivery.id)
        ):
            deliveries[d.notification_id].append(_delivery(d))
    return InboxOut(
        items=[
            NotificationOut(
                id=n.id,
                source=n.source,
                subject=n.subject,
                severity=n.severity,
                title=n.title,
                body=n.body,
                link=n.link,
                created_at=n.created_at,
                read_at=n.read_at,
                deliveries=deliveries[n.id],
            )
            for n in rows
        ],
        total=total,
        unread=_unread(db),
    )


@router.get("/unread", response_model=CountOut)
def unread_count(_user: UserDep, db: DbDep) -> CountOut:
    return CountOut(unread=_unread(db))


@router.post("/read", response_model=CountOut)
def mark_read(body: ReadIn, _user: UserDep, db: DbDep) -> CountOut:
    """Mark items read (or unread again), by id or all at once."""
    if not body.ids and not body.all:
        raise ApiError(422, "Nothing chosen", "Choose the items, or all.")
    stmt = update(Notification).values(read_at=utcnow() if body.read else None)
    if not body.all:
        stmt = stmt.where(Notification.id.in_(body.ids))
    elif body.read:
        stmt = stmt.where(Notification.read_at.is_(None))
    db.execute(stmt)
    db.flush()
    return CountOut(unread=_unread(db))


@router.get("/deliveries", response_model=list[DeliveryOut])
def deliveries(
    _user: UserDep,
    db: DbDep,
    status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[DeliveryOut]:
    """The delivery log, newest first: every push per channel, with retries and errors."""
    query = select(NotificationDelivery).order_by(NotificationDelivery.id.desc()).limit(limit)
    if status:
        query = query.where(NotificationDelivery.status.in_(status.split(",")))
    return [_delivery(d) for d in db.scalars(query)]


@router.post("/test/{channel}", response_model=TestOut)
def send_test(
    channel: str, request: Request, _user: UserDep, db: DbDep, store: StoreDep
) -> TestOut:
    """Send a test push through one channel now, with the saved settings (FR-NT-02)."""
    if channel not in CHANNELS:
        raise ApiError(404, "Not found", f"Unknown channel {channel!r}.")
    # tests inject a scripted transport; in production it is None and httpx goes out
    built = build_channels(db, store.get, request.app.state.provider_transport)
    target = built.get(channel)
    if target is None:
        return TestOut(ok=False, error="Not set up: save the address and token first.")
    settings = notification_settings(db)
    link = None if not settings.app_url else settings.app_url.rstrip("/") + "/insights"
    try:
        target.send(
            PushMessage(
                title="Folio test",
                body="This is a test push from Folio. It works.",
                severity="info",
                link=link,
            )
        )
    except ChannelError as exc:
        return TestOut(ok=False, error=str(exc))
    return TestOut(ok=True, error=None)
