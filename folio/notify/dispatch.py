"""Sending what the inbox has queued (FR-NT-03 to FR-NT-08, ADR 0023).

Runs every minute in the worker. For each due delivery it decides, in this order:
- critical goes out at once, through quiet hours and past the daily cap;
- in quiet hours everything else is held until they end (FR-NT-04);
- items on the same subject within an hour become one push, "3 updates on ..." (FR-NT-05);
- past the daily push cap the rest wait for the next day (FR-NT-04);
- the text is the lock-screen version: no euro amounts, and no names in the private mode
  (FR-NT-07);
- a failed send is retried twice, after one and five minutes, and every attempt is logged
  with the channel's own error (FR-NT-08).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from folio.db.models_strategy import Notification, NotificationDelivery
from folio.notify.channels import Channel, ChannelError, PushMessage
from folio.notify.service import notification_settings
from folio.settings_schema import GeneralSettings, NotificationsSettings
from folio.settings_store import load_section

MAX_ATTEMPTS = 3
BACKOFF = (timedelta(minutes=1), timedelta(minutes=5))
MERGE_WINDOW = timedelta(hours=1)
GENERIC_TITLE = {
    "critical": "Folio: urgent",
    "high": "Folio: important",
    "medium": "Folio",
    "low": "Folio",
    "info": "Folio",
}
NOT_SET_UP = "Not set up: add the address and token under Settings, Notifications."


@dataclass
class DispatchResult:
    sent: int = 0
    held: int = 0
    merged: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _hhmm(text: str) -> time:
    hours, minutes = text.split(":")
    return time(int(hours), int(minutes))


def in_quiet_hours(moment: time, start: time, end: time) -> bool:
    if start == end:
        return False
    if start < end:
        return start <= moment < end
    return moment >= start or moment < end  # the window crosses midnight


def quiet_ends_at(local: datetime, end: time) -> datetime:
    """The next moment the quiet window ends, after `local`."""
    candidate = local.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    return candidate if candidate > local else candidate + timedelta(days=1)


def push_text(n: Notification, settings: NotificationsSettings, count: int = 1) -> tuple[str, str]:
    private = settings.push_privacy == "names"
    title = n.push_title if n.source == "digest" else GENERIC_TITLE.get(n.severity, "Folio")
    if count > 1:
        return title, f"{count} updates" if private else f"{count} updates on {n.subject}"
    return title, n.push_body_anonymous if private else n.push_body


def _absolute(link: str | None, settings: NotificationsSettings) -> str | None:
    if not link or not settings.app_url:
        return None
    return settings.app_url.rstrip("/") + link


def dispatch(db: Session, now: datetime, channels: Mapping[str, Channel]) -> DispatchResult:
    settings = notification_settings(db)
    general = GeneralSettings.model_validate(load_section(db, "general").model_dump())
    zone = ZoneInfo(general.timezone)
    local = now.astimezone(zone)
    start, end = _hhmm(settings.quiet_hours_start), _hhmm(settings.quiet_hours_end)
    quiet = in_quiet_hours(local.time(), start, end)
    result = DispatchResult()

    rows = db.execute(
        select(NotificationDelivery, Notification)
        .join(Notification, Notification.id == NotificationDelivery.notification_id)
        .where(
            NotificationDelivery.status.in_(("queued", "held")),
            (NotificationDelivery.next_attempt_at.is_(None))
            | (NotificationDelivery.next_attempt_at <= now),
        )
        .order_by(Notification.created_at, Notification.id)
    ).all()
    if not rows:
        return result

    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    pushed_today = (
        db.scalar(
            select(func.count(func.distinct(NotificationDelivery.notification_id)))
            .join(Notification, Notification.id == NotificationDelivery.notification_id)
            .where(
                NotificationDelivery.status == "sent",
                NotificationDelivery.sent_at >= midnight,
                Notification.severity != "critical",
            )
        )
        or 0
    )
    counted_today: set[int] = set()

    groups: dict[tuple[str, str], list[tuple[NotificationDelivery, Notification]]] = defaultdict(
        list
    )
    for delivery, item in rows:
        groups[(delivery.channel, item.subject)].append((delivery, item))

    for (channel_name, subject), items in groups.items():
        channel = channels.get(channel_name)
        if channel is None:
            for delivery, _ in items:
                delivery.status, delivery.last_error = "skipped", NOT_SET_UP
                result.skipped += 1
            continue
        for delivery, item in [x for x in items if x[1].severity == "critical"]:
            _send(delivery, [delivery], item, channel, settings, now, result)
        others = [x for x in items if x[1].severity != "critical"]
        if not others:
            continue
        if quiet:
            _hold(others, quiet_ends_at(local, end).astimezone(UTC), result)
            continue
        last_sent = db.scalar(
            select(func.max(NotificationDelivery.sent_at))
            .join(Notification, Notification.id == NotificationDelivery.notification_id)
            .where(
                NotificationDelivery.channel == channel_name,
                NotificationDelivery.status == "sent",
                Notification.subject == subject,
                Notification.severity != "critical",
            )
        )
        if last_sent is not None and now - last_sent < MERGE_WINDOW:
            _hold(others, last_sent + MERGE_WINDOW, result)  # gathered into one push then
            continue
        ids = {item.id for _, item in others}
        new_ids = ids - counted_today
        if new_ids and pushed_today + 1 > settings.daily_push_cap:
            tomorrow = quiet_ends_at(local.replace(hour=23, minute=59), end)
            _hold(others, tomorrow.astimezone(UTC), result)
            continue
        primary, first_item = others[0]
        if _send(
            primary, [d for d, _ in others], first_item, channel, settings, now, result, len(others)
        ):
            if new_ids:
                pushed_today += 1
                counted_today |= ids
            for delivery, _ in others[1:]:
                delivery.status, delivery.merged_into_id = "merged", primary.id
                delivery.sent_at = now
                result.merged += 1
    db.flush()
    return result


def _hold(
    items: list[tuple[NotificationDelivery, Notification]], until: datetime, result: DispatchResult
) -> None:
    for delivery, _ in items:
        delivery.status, delivery.next_attempt_at = "held", until
        result.held += 1


def _send(
    primary: NotificationDelivery,
    group: list[NotificationDelivery],
    item: Notification,
    channel: Channel,
    settings: NotificationsSettings,
    now: datetime,
    result: DispatchResult,
    count: int = 1,
) -> bool:
    title, body = push_text(item, settings, count)
    message = PushMessage(
        title=title,
        body=body,
        severity=item.severity,
        link=_absolute(item.link, settings),
        tag=None if settings.push_privacy == "names" else item.subject,
    )
    primary.attempts += 1
    try:
        channel.send(message)
    except ChannelError as exc:
        primary.last_error = str(exc)
        result.errors.append(f"{channel.name}: {exc}")
        if primary.attempts >= MAX_ATTEMPTS:
            for delivery in group:
                delivery.status = "failed"
                delivery.last_error = str(exc)
            result.failed += 1
        else:
            wait = BACKOFF[min(primary.attempts - 1, len(BACKOFF) - 1)]
            for delivery in group:  # the group is retried together, as one push
                delivery.status, delivery.next_attempt_at = "queued", now + wait
        return False
    primary.status, primary.sent_at, primary.last_error = "sent", now, None
    result.sent += 1
    return True
