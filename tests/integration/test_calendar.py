# ruff: noqa: F811  (the fixtures are imported from other test modules and used as parameters)
"""The event calendar (FR-NW-09): ready-made and EODHD dates, your own events, the tool the agent
reads, and the brief or reminder the evening before."""

import datetime as dt
from collections.abc import Callable
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from folio.agent.facts import FactsBuilder
from folio.agent.tools import ToolBox
from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import AuditLog
from folio.db.models_insight import AgentRun, CalendarEvent
from folio.db.models_ledger import JobRequest, ProviderCall
from folio.db.models_strategy import Notification
from folio.jobs.calendar import calendar_job, event_briefs_job
from folio.jobs.context import JobContext
from folio.marketdata.budget import UsageTracker
from folio.marketdata.eodhd import EodhdProvider
from folio.marketdata.fallback import ProviderChain
from folio.news.calendar import sync_shipped
from folio.settings_schema import AgentSettings, CalendarSettings
from tests.agent_helpers import ScriptedLlm
from tests.conftest import PASSWORD, USERNAME
from tests.integration.test_agent_run import Brain, settings_save, world  # noqa: F401
from tests.integration.test_news_pipeline import book, db  # noqa: F401
from tests.marketdata_helpers import Scripted, client, make_listing, respond

D = Decimal
# 19:30 in Amsterdam on Tuesday 6 October 2026 (CEST)
EVENING = dt.datetime(2026, 10, 6, 17, 30, tzinfo=dt.UTC)
TOMORROW = dt.date(2026, 10, 7)


def ctx(
    settings: Settings,
    now: dt.datetime = EVENING,
    *,
    eodhd: Scripted | None = None,
    llm: ScriptedLlm | None = None,
    eodhd_budget: int = 20,
) -> JobContext:
    factory = make_session_factory(make_engine(settings.db_url))
    usage = UsageTracker(factory, lambda p: eodhd_budget if p == "eodhd" else 0)
    return JobContext(
        session_factory=factory,
        chain_for=lambda s: ProviderChain([]),
        ecb_for=lambda s: None,  # type: ignore[arg-type, return-value]
        now=lambda: now,
        usage=usage,
        eodhd_for=lambda s: (
            None
            if eodhd is None
            else EodhdProvider(client("eodhd", eodhd, usage=usage), "fake-eodhd-key-1234")
        ),
        llm_for=lambda s: None if llm is None else llm.client(),
    )


def turn_on_earnings(db: Session) -> None:
    from folio.security.secrets import SecretStore
    from folio.settings_store import save_section
    from tests.conftest import TEST_SECRET

    save_section(
        db, SecretStore(db, TEST_SECRET), "calendar", CalendarSettings(earnings_eodhd=True)
    )
    db.commit()


def live_events(db: Session) -> list[CalendarEvent]:
    db.expire_all()
    return list(
        db.scalars(
            select(CalendarEvent)
            .where(CalendarEvent.deleted_at.is_(None))
            .order_by(CalendarEvent.event_date, CalendarEvent.id)
        )
    )


# --- the dates ------------------------------------------------------------------------------------


def test_the_ready_made_dates_are_written_once_and_a_deleted_one_stays_deleted(
    settings: Settings, db: Session
) -> None:
    first = calendar_job(ctx(settings))
    assert first.status == "ok" and "16 added" in first.log
    assert "switched off" in first.log  # earnings from EODHD are off until you turn them on
    assert calendar_job(ctx(settings)).log.splitlines()[0].endswith("0 added.")
    rows = live_events(db)
    assert len(rows) == 16
    victim = next(r for r in rows if r.external_id == "fomc-2026-10-28")
    victim.deleted_at = dt.datetime(2026, 10, 6, tzinfo=dt.UTC)
    db.commit()
    calendar_job(ctx(settings))
    assert len(live_events(db)) == 15  # not brought back
    assert sync_shipped(db) == 0


def test_earnings_of_a_held_equity_come_from_eodhd_and_follow_a_rescheduling(
    settings: Settings, db: Session
) -> None:
    asml, _ = make_listing(
        db, ticker="ASML", mic="XAMS", isin="NL0010273215", symbols={"eodhd": "ASML.AS"}
    )
    asml.name, asml.asset_class = "ASML Holding", "EQUITY"
    make_listing(db, ticker="WRLD", isin="IE00B5BMR087", symbols={"eodhd": "WRLD.XETRA"})  # an ETF
    db.commit()
    turn_on_earnings(db)
    answer = Scripted(lambda r: respond("eodhd_earnings.json"))
    result = calendar_job(ctx(settings, eodhd=answer))
    assert result.status == "ok" and "Earnings dates: 1 added, 0 moved." in result.log
    (request,) = answer.requests
    assert request.url.params["symbols"] == "ASML.AS"  # the ETF is not asked about
    assert request.url.params["from"] == "2026-10-06" and request.url.params["to"] == "2026-12-05"
    assert db.scalar(select(ProviderCall.count).where(ProviderCall.provider == "eodhd")) == 1
    (earnings,) = [e for e in live_events(db) if e.kind == "earnings"]
    assert (earnings.title, earnings.event_date, earnings.source) == (
        "ASML Holding reports earnings",
        dt.date(2026, 10, 14),
        "eodhd",
    )
    assert earnings.detail == "before the market opens, expected earnings per share 5.32"

    earnings.brief_sent_at = EVENING
    db.commit()
    moved = Scripted(
        lambda r: httpx.Response(
            200,
            json={
                "earnings": [
                    {"code": "ASML.AS", "report_date": "2026-10-16", "date": "2026-09-30"},
                ]
            },
        )
    )
    again = calendar_job(ctx(settings, eodhd=moved))
    assert "0 added, 1 moved" in again.log
    (earnings,) = [e for e in live_events(db) if e.kind == "earnings"]
    assert earnings.event_date == dt.date(2026, 10, 16) and earnings.brief_sent_at is None


def test_earnings_need_a_key_a_plan_and_budget_and_never_stop_the_rest(
    settings: Settings, db: Session
) -> None:
    asml, _ = make_listing(
        db, ticker="ASML", mic="XAMS", isin="NL0010273215", symbols={"eodhd": "ASML.AS"}
    )
    asml.asset_class = "EQUITY"
    db.commit()
    turn_on_earnings(db)
    no_key = calendar_job(ctx(settings))
    assert "they need an EODHD API key" in no_key.log and no_key.status == "ok"
    refused = Scripted(lambda r: httpx.Response(403, text="forbidden"))
    plan = calendar_job(ctx(settings, eodhd=refused))
    assert plan.status == "failed" and "ERROR Earnings dates:" in plan.log
    assert len(live_events(db)) == 16  # the ready-made dates were written before the call
    poor = Scripted(lambda r: respond("eodhd_earnings.json"))
    kept = calendar_job(ctx(settings, eodhd=poor, eodhd_budget=3))
    assert "kept for the closes" in kept.log and poor.requests == []


# --- the tool and the API -------------------------------------------------------------------------


def test_the_agent_reads_the_upcoming_events_with_their_dates(
    settings: Settings, db: Session
) -> None:
    calendar_job(ctx(settings))
    box = ToolBox(db, EVENING, True, FactsBuilder())
    result, failed = box.run("get_upcoming_events", {"days": 30})
    assert not failed
    assert [(e["date"], e["in_days"]) for e in result["events"]] == [
        ("2026-10-28", 22),
        ("2026-10-29", 23),
    ]
    assert result["events"][1]["title"] == "ECB monetary policy decision"
    nothing, _ = box.run("get_upcoming_events", {"days": 5})
    assert nothing["events"] == [] and nothing["note"] == "No dated events in this window."


@pytest.fixture
def api(make_client: Callable[..., TestClient], owner: None) -> TestClient:
    c = make_client()
    c.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return c


def test_you_add_change_and_remove_events_and_it_is_audited(api: TestClient, db: Session) -> None:
    made = api.post(
        "/api/v1/calendar/events",
        json={
            "title": "  Annual meeting  ",
            "date": "2099-05-01",
            "detail": "vote on the dividend",
        },
    )
    assert made.status_code == 201, made.text
    event = made.json()
    assert (event["title"], event["kind"], event["source"]) == ("Annual meeting", "custom", "owner")
    assert event["brief_done"] is False
    event_id = event["id"]

    moved = api.patch(f"/api/v1/calendar/events/{event_id}", json={"date": "2099-05-02"})
    assert moved.json()["date"] == "2099-05-02"
    assert (
        api.post(
            "/api/v1/calendar/events",
            json={"title": "x", "date": "2099-05-02", "instrument_id": 999},
        ).status_code
        == 422
    )
    assert (
        api.post("/api/v1/calendar/events", json={"title": "   ", "date": "2099-05-02"}).status_code
        == 422
    )

    listed = api.get("/api/v1/calendar/events?days=180").json()
    assert [e["title"] for e in listed] == []  # 2099 is beyond a 180-day window
    db.expire_all()
    rows = db.scalars(select(AuditLog).where(AuditLog.entity == "calendar_event")).all()
    assert [r.action for r in rows] == ["create", "update"]

    assert api.delete(f"/api/v1/calendar/events/{event_id}").status_code == 204
    assert api.delete(f"/api/v1/calendar/events/{event_id}").status_code == 404
    assert api.patch(f"/api/v1/calendar/events/{event_id}", json={"title": "x"}).status_code == 404


def test_the_list_covers_a_window_and_a_refresh_is_queued(api: TestClient, db: Session) -> None:
    today = dt.datetime.now(dt.UTC).date()
    for offset, title in ((-3, "past"), (2, "soon"), (40, "later"), (200, "far")):
        api.post(
            "/api/v1/calendar/events",
            json={"title": title, "date": (today + dt.timedelta(days=offset)).isoformat()},
        )
    assert [e["title"] for e in api.get("/api/v1/calendar/events?days=60").json()] == [
        "soon",
        "later",
    ]
    with_past = api.get("/api/v1/calendar/events?days=60&past_days=7").json()
    assert [e["title"] for e in with_past] == ["past", "soon", "later"]
    assert with_past[1]["in_days"] == 2
    assert api.post("/api/v1/calendar/refresh").status_code == 202
    db.expire_all()
    assert (
        db.scalar(select(func.count()).select_from(JobRequest).where(JobRequest.job == "calendar"))
        == 1
    )


def test_the_calendar_needs_a_login(client: TestClient, owner: None) -> None:
    assert client.get("/api/v1/calendar/events").status_code == 401


# --- the evening before ---------------------------------------------------------------------------


def an_event(
    db: Session, day: dt.date = TOMORROW, title: str = "ECB monetary policy decision"
) -> int:
    event = CalendarEvent(kind="central_bank", event_date=day, title=title, source="owner")
    db.add(event)
    db.commit()
    return event.id


def titles(db: Session) -> list[str]:
    db.expire_all()
    return [n.title for n in db.scalars(select(Notification).order_by(Notification.id))]


def test_an_event_tomorrow_gets_a_brief_in_insights_once(
    settings: Settings, db: Session, world
) -> None:
    event_id = an_event(db)
    llm = ScriptedLlm(handler=Brain(compose=lambda calc: []))
    result = event_briefs_job(ctx(settings, llm=llm))
    assert result.status == "ok" and "Brief for 'ECB monetary policy decision' made." in result.log
    assert any(t.startswith("Event brief:") for t in titles(db))
    assert not any(t.startswith("Tomorrow:") for t in titles(db))  # the brief replaces the reminder
    run = db.scalars(select(AgentRun).where(AgentRun.run_type == "event_brief")).one()
    assert run.trigger == f"event-brief:{event_id}" and run.model == "claude-sonnet-5-5"
    assert "ECB monetary policy decision" in str(run.context["focus"])
    assert db.get(CalendarEvent, event_id).brief_sent_at is not None  # type: ignore[union-attr]
    again = event_briefs_job(ctx(settings, llm=llm))
    assert "made" not in again.log
    assert (
        db.scalar(
            select(func.count()).select_from(AgentRun).where(AgentRun.run_type == "event_brief")
        )
        == 1
    )


def test_without_the_agent_a_plain_reminder_goes_out_instead(
    settings: Settings, db: Session
) -> None:
    an_event(db)
    result = event_briefs_job(ctx(settings))  # no model client: off, or no key
    assert "Reminder for 'ECB monetary policy decision' sent" in result.log
    (item,) = db.scalars(select(Notification)).all()
    assert item.title == "Tomorrow: ECB monetary policy decision" and item.source == "digest"
    assert item.push_body_anonymous == "An event you follow is tomorrow."
    assert item.link == "/news?tab=calendar"


def test_when_the_budget_is_used_up_the_reminder_still_goes_out(
    settings: Settings, db: Session, world
) -> None:
    an_event(db)
    settings_save(db, monthly_budget_eur=D("0"))
    llm = ScriptedLlm(handler=Brain(compose=lambda calc: []))
    result = event_briefs_job(ctx(settings, llm=llm))
    assert "Reminder for" in result.log
    assert llm.requests == []  # the budget guard stopped the call before it was made
    assert any(t.startswith("Tomorrow:") for t in titles(db))


def test_nothing_goes_out_before_18_00_or_for_other_days(settings: Settings, db: Session) -> None:
    an_event(db)
    an_event(db, dt.date(2026, 10, 9), "Later")
    an_event(db, dt.date(2026, 10, 6), "Today")
    afternoon = dt.datetime(2026, 10, 6, 15, 59, tzinfo=dt.UTC)  # 17:59 in Amsterdam
    assert event_briefs_job(ctx(settings, afternoon)).log == ""
    assert titles(db) == []
    event_briefs_job(ctx(settings, afternoon + dt.timedelta(minutes=2)))
    assert titles(db) == ["Tomorrow: ECB monetary policy decision"]  # only tomorrow's
    assert AgentSettings().models["event_brief"] == "claude-sonnet-5-5"
