"""The inbox (FR-NT-01): every notification is stored first, then queued per phone channel by
the routing matrix as it is at that moment (FR-NT-03). The dispatcher sends what is queued.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.db.models_strategy import Notification, NotificationDelivery, Signal
from folio.events import publish_event
from folio.notify.channels import Channel, HomeAssistantChannel, NtfyChannel
from folio.settings_schema import NotificationsSettings
from folio.settings_store import load_section

NOTIFICATION = "notification"  # the event the browser's bell listens for


def notification_settings(db: Session) -> NotificationsSettings:
    return NotificationsSettings.model_validate(load_section(db, "notifications").model_dump())


def next_hour(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


def notify(
    db: Session,
    *,
    source: str,
    severity: str,
    subject: str,
    title: str,
    body: str,
    push_title: str | None = None,
    push_body: str,
    push_body_anonymous: str,
    link: str | None = None,
    signal_id: int | None = None,
    now: datetime,
) -> Notification:
    """Store an inbox item and queue its pushes. Medium items wait for the next full hour, so
    they go out together (batched hourly)."""
    item = Notification(
        source=source,
        subject=subject[:120],
        severity=severity,
        title=title[:200],
        body=body,
        push_title=(push_title or "Folio")[:200],  # only a digest has its own push title
        push_body=push_body[:400],
        push_body_anonymous=push_body_anonymous[:400],
        link=link,
        signal_id=signal_id,
        created_at=now,
    )
    db.add(item)
    db.flush()
    settings = notification_settings(db)
    if settings.channel != "none":
        route = "digest" if source == "digest" else severity
        due = next_hour(now) if severity == "medium" and source != "digest" else None
        for channel in dict.fromkeys(settings.routing.get(route, [])):  # type: ignore[call-overload]
            db.add(
                NotificationDelivery(
                    notification_id=item.id, channel=channel, status="queued", next_attempt_at=due
                )
            )
    publish_event(db, NOTIFICATION, {"id": item.id, "severity": severity})
    db.flush()
    return item


def _signal_link(signal: Signal) -> str:
    payload: dict[str, Any] = signal.payload or {}
    if payload.get("instrument_id"):
        return f"/holdings/{payload['instrument_id']}"
    return "/strategies" if signal.strategy_version_id is not None else "/insights"


def consume_signals(db: Session, now: datetime) -> int:
    """New signals of the active strategy (and price alerts) become notifications; shadow
    signals stay on the Strategies page only (FR-ST-02). Returns how many were created."""
    created = 0
    for signal in db.scalars(
        select(Signal).where(Signal.state == "new", Signal.shadow.is_(False)).order_by(Signal.id)
    ):
        payload: dict[str, Any] = signal.payload or {}
        notify(
            db,
            source="signal" if signal.strategy_version_id is not None else "alert",
            severity=signal.severity,
            subject=signal.subject,
            title=str(payload.get("title") or signal.message)[:200],
            body=signal.message,
            push_body=str(payload.get("push") or payload.get("title") or ""),
            push_body_anonymous=str(payload.get("push_anonymous") or "Folio has a new item."),
            link=_signal_link(signal),
            signal_id=signal.id,
            now=now,
        )
        signal.state = "consumed"
        created += 1
    db.flush()
    return created


def build_channels(
    db: Session,
    get_secret: Callable[[str], str | None],
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Channel]:
    """The phone channels that are set up: Home Assistant needs its address, the notify
    service and a token; ntfy needs its address and a topic (a token is optional)."""
    settings = notification_settings(db)
    out: dict[str, Channel] = {}
    token = get_secret("notifications.home_assistant_token")
    if settings.home_assistant_url and settings.home_assistant_service and token:
        out["home_assistant"] = HomeAssistantChannel(
            settings.home_assistant_url, settings.home_assistant_service, token, transport
        )
    if settings.ntfy_url and settings.ntfy_topic:
        out["ntfy"] = NtfyChannel(
            settings.ntfy_url,
            settings.ntfy_topic,
            get_secret("notifications.ntfy_token"),
            transport,
        )
    return out
