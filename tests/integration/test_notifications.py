"""The inbox, the phone channels and the dispatcher (FR-NT-01 to FR-NT-08)."""

import json
import re
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models_strategy import Notification, NotificationDelivery, Signal
from folio.jobs.context import JobContext
from folio.jobs.notify import notify_job
from folio.marketdata.ecb import EcbRates
from folio.marketdata.fallback import ProviderChain
from folio.notify.channels import ChannelError, HomeAssistantChannel, NtfyChannel, PushMessage
from folio.notify.digest import build_digest
from folio.notify.dispatch import dispatch, in_quiet_hours
from folio.notify.service import consume_signals, notify
from folio.settings_schema import NotificationsSettings
from folio.settings_store import set_value
from tests.conftest import PASSWORD, USERNAME
from tests.marketdata_helpers import Scripted, client

# A winter weekday: Amsterdam is UTC+1, so 10:00 local is 09:00 UTC.
DAY = date(2025, 1, 15)


def at(hour: int, minute: int = 0, day: date = DAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour - 1, minute, tzinfo=UTC)  # local -> UTC


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


class Phone:
    """A channel that records what it was asked to send, and can be made to fail."""

    def __init__(self, name: str, fail: str | None = None) -> None:
        self.name = name
        self.sent: list[PushMessage] = []
        self.fail = fail

    def send(self, message: PushMessage) -> None:
        if self.fail:
            raise ChannelError(self.fail)
        self.sent.append(message)


def configure(db: Session, **values: Any) -> None:
    base = NotificationsSettings().model_dump(mode="json")
    base.update(values)
    set_value(
        db, "section.notifications", {k: v for k, v in base.items() if not k.endswith("_token")}
    )
    db.commit()


def item(
    db: Session,
    severity: str = "high",
    subject: str = "equity",
    now: datetime | None = None,
    **over: Any,
) -> Notification:
    fields: dict[str, Any] = {
        "source": "signal",
        "severity": severity,
        "subject": subject,
        "title": f"{subject} is 12.0 pp over its target",
        "body": f"{subject} weighs 62% against 50%. Worth 1,234.56 EUR more than its target.",
        "push_body": f"{subject} is 12.0 pp over its target.",
        "push_body_anonymous": "A sleeve is outside its hard band.",
        "link": "/strategies",
        "now": now or at(10),
    }
    fields.update(over)
    created = notify(db, **fields)
    db.commit()
    return created


def deliveries(db: Session) -> list[NotificationDelivery]:
    db.expire_all()
    return list(db.scalars(select(NotificationDelivery).order_by(NotificationDelivery.id)))


# --- channels -----------------------------------------------------------------------------------


def test_home_assistant_gets_the_documented_service_call() -> None:
    scripted = Scripted(lambda r: httpx.Response(200, json=[]))
    HomeAssistantChannel(
        "http://ha.local:8123/", "notify.mobile_app_phone", "ha-token-123456", scripted.transport
    ).send(
        PushMessage(
            "Folio: important",
            "equity is 12.0 pp over its target.",
            "critical",
            "https://folio.example/strategies",
            "equity",
        )
    )
    (request,) = scripted.requests
    assert str(request.url) == "http://ha.local:8123/api/services/notify/mobile_app_phone"
    assert request.headers["Authorization"] == "Bearer ha-token-123456"
    body = json.loads(request.content)
    assert body["title"] == "Folio: important" and body["message"].startswith("equity")
    assert body["data"]["url"] == body["data"]["clickAction"] == "https://folio.example/strategies"
    assert body["data"]["push"] == {"interruption-level": "time-sensitive"}  # critical


def test_ntfy_gets_json_with_topic_priority_and_click() -> None:
    scripted = Scripted(lambda r: httpx.Response(200, json={"id": "x"}))
    NtfyChannel("https://ntfy.example", "folio", "tk_123456", scripted.transport).send(
        PushMessage("Folio", "Grüße: equity is over", "high", "https://folio.example/x", "equity")
    )
    (request,) = scripted.requests
    body = json.loads(request.content)
    assert str(request.url) == "https://ntfy.example"
    assert (body["topic"], body["priority"], body["click"], body["message"]) == (
        "folio",
        4,
        "https://folio.example/x",
        "Grüße: equity is over",
    )
    assert request.headers["Authorization"] == "Bearer tk_123456"


def test_channel_failures_read_like_the_problem() -> None:
    refused = Scripted(lambda r: httpx.Response(401))
    with pytest.raises(ChannelError, match="refused the token"):
        HomeAssistantChannel("http://ha", "x", "t" * 10, refused.transport).send(
            PushMessage("a", "b", "low")
        )

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(ChannelError, match="could not be reached"):
        NtfyChannel("https://ntfy.example", "t", None, Scripted(down).transport).send(
            PushMessage("a", "b", "low")
        )


# --- routing ------------------------------------------------------------------------------------


def test_the_routing_matrix_decides_the_channels_of_the_next_item(db) -> None:  # type: ignore[no-untyped-def]
    item(db, "high")
    assert [d.channel for d in deliveries(db)] == ["home_assistant", "ntfy"]
    item(db, "low", subject="gold")
    assert len(deliveries(db)) == 2  # low stays in the inbox
    configure(db, routing={**NotificationsSettings().routing, "high": ["ntfy"]})
    item(db, "high", subject="bonds")
    assert [d.channel for d in deliveries(db)][2:] == ["ntfy"]
    configure(db, channel="none")
    item(db, "critical", subject="cash")
    assert len(deliveries(db)) == 3  # phone pushes switched off


def test_a_channel_that_is_not_set_up_is_skipped_and_says_why(db) -> None:  # type: ignore[no-untyped-def]
    item(db, "high")
    dispatch(db, at(10, 1), {"ntfy": Phone("ntfy")})
    statuses = {d.channel: (d.status, d.last_error) for d in deliveries(db)}
    assert statuses["ntfy"] == ("sent", None)
    assert (
        statuses["home_assistant"][0] == "skipped"
        and "Settings, Notifications" in statuses["home_assistant"][1]
    )


# --- quiet hours, cap, batching, merging --------------------------------------------------------


def test_no_high_push_at_23_00_it_waits_for_07_30_but_critical_goes_through(db) -> None:  # type: ignore[no-untyped-def]
    configure(
        db, routing={**NotificationsSettings().routing, "high": ["ntfy"], "critical": ["ntfy"]}
    )
    phone = Phone("ntfy")
    item(db, "high", now=at(23))
    item(db, "critical", subject="portfolio", now=at(23))
    dispatch(db, at(23, 1), {"ntfy": phone})
    assert [m.severity for m in phone.sent] == ["critical"]
    held = next(d for d in deliveries(db) if d.status == "held")
    assert held.next_attempt_at == at(7, 30, DAY + timedelta(days=1))
    dispatch(db, at(7, 29, DAY + timedelta(days=1)), {"ntfy": phone})
    assert len(phone.sent) == 1
    dispatch(db, at(7, 30, DAY + timedelta(days=1)), {"ntfy": phone})
    assert [m.severity for m in phone.sent] == ["critical", "high"]
    window = (time(22), time(7, 30))
    assert in_quiet_hours(time(23), *window) and in_quiet_hours(time(6), *window)
    assert not in_quiet_hours(time(12), *window) and not in_quiet_hours(time(7, 30), *window)
    assert not in_quiet_hours(time(3), time(0), time(0))  # an empty window


def test_the_daily_cap_holds_the_sixth_push_but_not_critical_ones(db) -> None:  # type: ignore[no-untyped-def]
    configure(
        db, routing={**NotificationsSettings().routing, "high": ["ntfy"], "critical": ["ntfy"]}
    )
    phone = Phone("ntfy")
    for n in range(6):
        item(db, "high", subject=f"sleeve {n}")
    item(db, "critical", subject="portfolio")
    dispatch(db, at(10, 1), {"ntfy": phone})
    assert len([m for m in phone.sent if m.severity == "high"]) == 5
    assert [m.severity for m in phone.sent].count("critical") == 1
    (held,) = [d for d in deliveries(db) if d.status == "held"]
    assert held.next_attempt_at == at(7, 30, DAY + timedelta(days=1))


def test_three_items_on_one_subject_become_one_push(db) -> None:  # type: ignore[no-untyped-def]
    configure(db, routing={**NotificationsSettings().routing, "high": ["ntfy"]})
    phone = Phone("ntfy")
    for _ in range(3):
        item(db, "high", subject="equity")
    dispatch(db, at(10, 1), {"ntfy": phone})
    (push,) = phone.sent
    assert push.body == "3 updates on equity"
    statuses = sorted(d.status for d in deliveries(db))
    assert statuses == ["merged", "merged", "sent"]
    # a fourth within the hour waits, and goes out with any others an hour after the first
    item(db, "high", subject="equity", now=at(10, 20))
    dispatch(db, at(10, 21), {"ntfy": phone})
    assert len(phone.sent) == 1
    dispatch(db, at(11, 1), {"ntfy": phone})
    assert len(phone.sent) == 2


def test_medium_items_are_batched_by_the_hour(db) -> None:  # type: ignore[no-untyped-def]
    configure(db, routing={**NotificationsSettings().routing, "medium": ["ntfy"]})
    phone = Phone("ntfy")
    item(db, "medium", subject="gold", now=at(10, 20))
    item(db, "medium", subject="bonds", now=at(10, 40))
    dispatch(db, at(10, 41), {"ntfy": phone})
    assert phone.sent == []
    dispatch(db, at(11, 0), {"ntfy": phone})
    assert len(phone.sent) == 2


# --- privacy and retries ------------------------------------------------------------------------


def test_pushes_carry_no_amounts_and_the_private_mode_no_names(db) -> None:  # type: ignore[no-untyped-def]
    configure(
        db,
        routing={**NotificationsSettings().routing, "high": ["ntfy"]},
        app_url="https://folio.example",
    )
    phone = Phone("ntfy")
    item(db, "high", subject="Secret Corp")
    dispatch(db, at(10, 1), {"ntfy": phone})
    (push,) = phone.sent
    assert not re.search(r"€|EUR|\d[\d.,]*\s*EUR", push.title + push.body)
    assert push.link == "https://folio.example/strategies" and push.tag == "Secret Corp"

    configure(
        db, routing={**NotificationsSettings().routing, "high": ["ntfy"]}, push_privacy="names"
    )
    item(db, "high", subject="Secret Corp", now=at(12))
    dispatch(db, at(12, 1), {"ntfy": phone})
    private = phone.sent[-1]
    assert "Secret Corp" not in private.body + private.title and private.tag is None
    assert private.body == "A sleeve is outside its hard band."


def test_a_failing_channel_is_retried_then_the_error_is_kept(db) -> None:  # type: ignore[no-untyped-def]
    configure(db, routing={**NotificationsSettings().routing, "high": ["ntfy"]})
    broken = Phone("ntfy", fail="ntfy answered HTTP 502.")
    item(db, "high")
    dispatch(db, at(10, 1), {"ntfy": broken})
    (d,) = deliveries(db)
    assert (d.status, d.attempts, d.next_attempt_at) == ("queued", 1, at(10, 2))
    dispatch(db, at(10, 2), {"ntfy": broken})
    (d,) = deliveries(db)
    assert (d.attempts, d.next_attempt_at) == (2, at(10, 7))
    dispatch(db, at(10, 7), {"ntfy": broken})
    (d,) = deliveries(db)
    assert (d.status, d.attempts, d.last_error) == ("failed", 3, "ntfy answered HTTP 502.")


# --- signals and digests ------------------------------------------------------------------------


def test_signals_become_inbox_items_but_shadow_ones_do_not(db) -> None:  # type: ignore[no-untyped-def]
    payload = {
        "title": "equity is 12 pp over",
        "push": "equity is 12 pp over.",
        "push_anonymous": "A sleeve is out.",
    }
    db.add(
        Signal(
            rule_id="d",
            rule_type="drift_band",
            subject="equity",
            severity="high",
            message="long",
            payload=payload,
            dedup_key="a",
            ts=at(10),
        )
    )
    db.add(
        Signal(
            rule_id="d",
            rule_type="drift_band",
            subject="gold",
            severity="high",
            message="long",
            payload=payload,
            dedup_key="b",
            shadow=True,
            ts=at(10),
        )
    )
    db.commit()
    assert consume_signals(db, at(10)) == 1
    db.commit()
    (n,) = db.scalars(select(Notification)).all()
    assert (n.subject, n.source, n.push_body, n.title) == (
        "equity",
        "alert",
        "equity is 12 pp over.",
        "equity is 12 pp over",
    )
    states = {s.subject: s.state for s in db.scalars(select(Signal))}
    assert states == {"equity": "consumed", "gold": "new"}


def test_the_daily_digest_lists_open_items_and_its_push_has_no_amounts(db) -> None:  # type: ignore[no-untyped-def]
    item(db, "high", now=at(9))
    item(db, "low", subject="gold", now=at(9))
    digest = build_digest(db, "daily", at(18, 30), DAY)
    db.commit()
    assert digest.source == "digest" and digest.title == "Daily summary, 2025-01-15"
    assert "2 open items" in digest.body and "[high] equity" in digest.body.replace(
        " is 12.0 pp over its target", ""
    )
    assert (
        digest.push_body == "Your daily summary is ready: 2 open items."
        and "EUR" not in digest.push_body
    )
    assert {d.channel for d in deliveries(db) if d.notification_id == digest.id} == {
        "home_assistant",
        "ntfy",
    }


def test_the_worker_writes_each_digest_once_after_its_time(settings: Settings, db) -> None:  # type: ignore[no-untyped-def]
    def ctx(now: datetime) -> JobContext:
        return JobContext(
            session_factory=make_session_factory(make_engine(settings.db_url)),
            chain_for=lambda s: ProviderChain([]),
            ecb_for=lambda s: EcbRates(client("ecb", Scripted(lambda r: httpx.Response(404)))),
            now=lambda: now,
        )

    sunday = date(2025, 1, 19)
    notify_job(ctx(at(18, 0, sunday)))
    assert db.scalars(select(Notification)).all() == []  # not yet 18:30
    notify_job(ctx(at(18, 31, sunday)))
    notify_job(ctx(at(18, 32, sunday)))
    db.expire_all()
    assert sorted(n.subject for n in db.scalars(select(Notification))) == [
        "daily digest",
        "weekly digest",
    ]
    notify_job(ctx(at(18, 31, sunday + timedelta(days=1))))
    db.expire_all()
    assert (
        sorted(n.subject for n in db.scalars(select(Notification))).count("daily digest") == 2
    )  # Monday: no weekly


# --- the API ------------------------------------------------------------------------------------


@pytest.fixture
def api(client: TestClient, owner: None) -> TestClient:  # noqa: F811
    client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return client


def test_the_inbox_filters_and_marks_read_in_bulk(api: TestClient, db) -> None:  # type: ignore[no-untyped-def]
    item(db, "high", subject="equity")
    item(db, "low", subject="gold")
    item(db, "medium", subject="Gold miners", source="alert")
    inbox = api.get("/api/v1/notifications").json()
    assert (inbox["total"], inbox["unread"]) == (3, 3)
    assert inbox["items"][0]["deliveries"]  # the delivery log per item
    assert [
        i["subject"]
        for i in api.get("/api/v1/notifications", params={"severity": "high,medium"}).json()[
            "items"
        ]
    ] == ["Gold miners", "equity"]
    assert [
        i["subject"]
        for i in api.get("/api/v1/notifications", params={"source": "alert"}).json()["items"]
    ] == ["Gold miners"]
    assert len(api.get("/api/v1/notifications", params={"subject": "gold"}).json()["items"]) == 2
    first = inbox["items"][0]["id"]
    assert api.post("/api/v1/notifications/read", json={"ids": [first]}).json() == {"unread": 2}
    assert len(api.get("/api/v1/notifications", params={"status": "read"}).json()["items"]) == 1
    assert api.post("/api/v1/notifications/read", json={"all": True}).json() == {"unread": 0}
    assert api.post("/api/v1/notifications/read", json={"ids": [first], "read": False}).json() == {
        "unread": 1
    }
    assert api.get("/api/v1/notifications/unread").json() == {"unread": 1}
    assert api.post("/api/v1/notifications/read", json={}).status_code == 422


def test_the_delivery_log_shows_a_failed_push_with_its_error(api: TestClient, db) -> None:  # type: ignore[no-untyped-def]
    configure(db, routing={**NotificationsSettings().routing, "high": ["ntfy"]})
    item(db, "high")
    broken = Phone("ntfy", fail="ntfy answered HTTP 502.")
    for minute in (1, 2, 7):
        dispatch(db, at(10, minute), {"ntfy": broken})
        db.commit()
    (log,) = api.get("/api/v1/notifications/deliveries", params={"status": "failed"}).json()
    assert (log["channel"], log["attempts"], log["last_error"]) == (
        "ntfy",
        3,
        "ntfy answered HTTP 502.",
    )


def test_send_test_reaches_the_channel_and_reports_its_error(make_client, owner: None) -> None:  # type: ignore[no-untyped-def]
    answers = iter([httpx.Response(200, json=[]), httpx.Response(401)])
    scripted = Scripted(lambda r: next(answers))
    api = make_client(provider_transport=scripted.transport)
    api.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    assert api.post("/api/v1/notifications/test/home_assistant").json() == {
        "ok": False,
        "error": "Not set up: save the address and token first.",
    }
    saved = api.put(
        "/api/v1/settings/notifications",
        json={
            "home_assistant_url": "http://ha.local:8123",
            "home_assistant_service": "mobile_app_phone",
            "home_assistant_token": "ha-token-123456",
        },
    )
    assert saved.status_code == 200, saved.text
    assert api.post("/api/v1/notifications/test/home_assistant").json() == {
        "ok": True,
        "error": None,
    }
    assert scripted.requests[0].url.path == "/api/services/notify/mobile_app_phone"
    failed = api.post("/api/v1/notifications/test/home_assistant").json()
    assert failed["ok"] is False and "refused the token" in failed["error"]
    assert api.post("/api/v1/notifications/test/pigeon").status_code == 404
