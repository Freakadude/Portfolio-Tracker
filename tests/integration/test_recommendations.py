# ruff: noqa: F811  (the fixtures are imported from other test modules and used as parameters)
"""The recommendation lifecycle (FR-AG-05): the open list, seen, accept (with drafts only while
the calculation holds), reject with a reason the next run can see, snooze, and expiry."""

import datetime as dt
from collections.abc import Callable
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.agent.facts import FactsBuilder
from folio.agent.lifecycle import expire_due
from folio.agent.run import run_agent
from folio.agent.tools import ToolBox
from folio.api.routers import recommendations as router_module
from folio.config import Settings
from folio.db.models import AuditLog
from folio.db.models_analytics import AppEvent
from folio.db.models_insight import Recommendation
from folio.db.models_ledger import LedgerTransaction
from folio.jobs.agent import agent_tick
from folio.ledger_service import TransactionIn, create_transaction
from tests.agent_helpers import ScriptedLlm
from tests.conftest import PASSWORD, USERNAME
from tests.integration.test_agent_run import Brain, job_ctx, rec, world  # noqa: F401
from tests.integration.test_news_pipeline import NOW, book, db  # noqa: F401

D = Decimal
LATER = NOW + dt.timedelta(hours=1)


@pytest.fixture
def api(
    make_client: Callable[..., TestClient], owner: None, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    monkeypatch.setattr(router_module, "utcnow", lambda: LATER)  # the book is from March 2024
    c = make_client()
    c.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return c


def made(db: Session, brain: Brain | None = None, trigger: str = "daily") -> list[int]:
    out = run_agent(
        db,
        ScriptedLlm(handler=brain or Brain()).client(),
        NOW,
        run_type="daily_review",
        trigger=trigger,
    )
    db.commit()
    return out.accepted


def decide(api: TestClient, rec_id: int, **body: object):  # type: ignore[no-untyped-def]
    return api.patch(f"/api/v1/recommendations/{rec_id}", json=body)


# --- the list -------------------------------------------------------------------------------------


def test_the_open_list_has_what_needs_a_decision_and_labels_it_as_ai(
    api: TestClient, db: Session, world
) -> None:
    (rec_id,) = made(db)
    listed = api.get("/api/v1/recommendations").json()
    assert [r["id"] for r in listed] == [rec_id]
    item = listed[0]
    assert (item["status"], item["action_type"], item["calculation_id"]) == (
        "new",
        "direct_contribution",
        1,
    )
    assert (
        item["ai_label"] == "AI-generated, not financial advice."
        and item["departs_from_principles"] is None
    )
    assert [e["kind"] for e in item["evidence"]] == ["signal", "metric"]
    assert item["expires_at"].startswith("2024-03-29")
    detail = api.get(f"/api/v1/recommendations/{rec_id}").json()
    assert [(o["side"], o["name"], o["quantity"], o["amount_eur"]) for o in detail["orders"]] == [
        ("buy", "Gold ETC", "10", "1000")
    ]
    assert detail["plan_current"] is True and D(detail["remainder_eur"]) == 0


def test_a_refused_item_is_not_advice_and_is_never_listed_or_opened(
    api: TestClient, db: Session, world
) -> None:
    made(db, Brain(compose=lambda calc: [rec(None, title="Sell it all")]))
    refused = db.scalar(select(Recommendation).where(Recommendation.status == "refused"))
    assert api.get("/api/v1/recommendations", params={"status": "all"}).json() == []
    assert api.get(f"/api/v1/recommendations/{refused.id}").status_code == 404
    assert decide(api, refused.id, action="accept").status_code == 404


def test_items_past_their_expiry_leave_the_open_list_by_themselves(
    api: TestClient, db: Session, world
) -> None:
    (rec_id,) = made(db)
    db.get(Recommendation, rec_id).expires_at = LATER + dt.timedelta(minutes=1)
    db.commit()
    assert [r["id"] for r in api.get("/api/v1/recommendations").json()] == [rec_id]
    db.get(Recommendation, rec_id).expires_at = LATER - dt.timedelta(
        minutes=1
    )  # the clock passes it
    db.commit()
    assert api.get("/api/v1/recommendations").json() == []  # no job has run, yet it is gone
    expired = api.get("/api/v1/recommendations", params={"status": "expired"}).json()
    assert [(r["id"], r["status"]) for r in expired] == [(rec_id, "expired")]
    assert decide(api, rec_id, action="accept").status_code == 409


def test_the_expiry_job_marks_items_and_wakes_snoozed_ones(db: Session, world) -> None:
    (rec_id,) = made(db)
    other = made(db, trigger="second")[0]
    db.get(Recommendation, rec_id).expires_at = NOW + dt.timedelta(days=1)
    row = db.get(Recommendation, other)
    row.status, row.snoozed_until = "snoozed", NOW + dt.timedelta(days=2)
    db.commit()
    assert expire_due(db, NOW + dt.timedelta(hours=12)) == (0, 0)
    assert expire_due(db, NOW + dt.timedelta(days=1, hours=1)) == (1, 0)
    assert db.get(Recommendation, rec_id).status == "expired"
    assert expire_due(db, NOW + dt.timedelta(days=2, hours=1)) == (0, 1)
    assert (
        db.get(Recommendation, other).status == "new"
        and db.get(Recommendation, other).snoozed_until is None
    )
    audit = db.scalars(select(AuditLog).where(AuditLog.entity == "recommendation")).all()
    assert [(a.actor, a.action) for a in audit] == [("worker", "expire")]


def test_the_worker_check_expires_items_even_when_the_agent_is_off(
    settings: Settings, db: Session, world
) -> None:
    (rec_id,) = made(db)
    db.get(Recommendation, rec_id).expires_at = NOW - dt.timedelta(minutes=1)
    db.commit()
    assert agent_tick(job_ctx(settings, None)) == 0  # no client: nothing to run, but expiry happens
    db.expire_all()
    assert db.get(Recommendation, rec_id).status == "expired"


# --- the decisions --------------------------------------------------------------------------------


def test_seen_moves_a_new_item_once_and_changes_nothing_else(
    api: TestClient, db: Session, world
) -> None:
    (rec_id,) = made(db)
    assert decide(api, rec_id, action="seen").json()["recommendation"]["status"] == "seen"
    assert decide(api, rec_id, action="seen").json()["recommendation"]["status"] == "seen"
    assert [r["id"] for r in api.get("/api/v1/recommendations").json()] == [rec_id]  # still open
    assert [
        r["status"] for r in api.get("/api/v1/recommendations", params={"status": "seen"}).json()
    ] == ["seen"]


def test_accepting_with_drafts_turns_the_calculation_into_draft_transactions(
    api: TestClient, db: Session, world
) -> None:
    (rec_id,) = made(db)
    out = decide(api, rec_id, action="accept", create_drafts=True)
    assert out.status_code == 200
    body = out.json()
    assert body["recommendation"]["status"] == "accepted" and len(body["drafts"]) == 1
    assert body["recommendation"]["linked_transaction_ids"] == body["drafts"]
    draft = db.get(LedgerTransaction, body["drafts"][0])
    assert (draft.type, draft.status, draft.source, draft.quantity) == (
        "buy",
        "draft",
        "strategy",
        D(10),
    )
    assert f"recommendation {rec_id}" in draft.note
    assert api.get("/api/v1/recommendations").json() == []  # no longer waiting
    assert [
        r["id"] for r in api.get("/api/v1/recommendations", params={"status": "accepted"}).json()
    ] == [rec_id]
    audit = db.scalars(
        select(AuditLog).where(AuditLog.entity == "recommendation", AuditLog.action == "accept")
    ).all()
    assert len(audit) == 1 and audit[0].diff["status"] == {"old": "new", "new": "accepted"}
    assert decide(api, rec_id, action="reject").status_code == 409  # a decision is final


def test_drafts_are_refused_once_the_calculation_no_longer_holds(
    api: TestClient, db: Session, world
) -> None:
    (rec_id,) = made(db)
    create_transaction(
        db,
        TransactionIn(
            account_id=1,
            instrument_id=world["gold"],
            type="buy",
            trade_date=NOW.date(),
            quantity=D(10),
            price=D(100),
        ),  # fmt: skip
    )
    db.commit()
    assert api.get(f"/api/v1/recommendations/{rec_id}").json()["plan_current"] is False
    refused = decide(api, rec_id, action="accept", create_drafts=True)
    assert refused.status_code == 409 and "out of date" in refused.json()["detail"]
    assert (
        db.scalars(select(LedgerTransaction).where(LedgerTransaction.status == "draft")).all() == []
    )
    assert api.get(f"/api/v1/recommendations/{rec_id}").json()["status"] == "new"  # nothing changed
    accepted = decide(api, rec_id, action="accept")  # the owner can still accept and record by hand
    assert (
        accepted.json()["recommendation"]["status"] == "accepted"
        and accepted.json()["drafts"] == []
    )


def test_an_item_without_an_order_list_cannot_be_turned_into_drafts(
    api: TestClient, db: Session, world
) -> None:
    watch = rec(None, action_type="watch", summary="Keep an eye on it.")
    (rec_id,) = made(db, Brain(compose=lambda calc: [watch]))
    refused = decide(api, rec_id, action="accept", create_drafts=True)
    assert refused.status_code == 422 and "no order list" in refused.json()["detail"]


def test_a_rejection_keeps_its_one_line_reason_and_the_next_run_sees_it(
    api: TestClient, db: Session, world
) -> None:
    (rec_id,) = made(db)
    note = "I never add to gold in March.\n\nSee my notes " + "x" * 400
    out = decide(api, rec_id, action="reject", note=note)
    assert out.status_code == 200
    saved = out.json()["recommendation"]
    assert (
        saved["status"] == "rejected"
        and "\n" not in saved["user_note"]
        and len(saved["user_note"]) == 300
    )
    assert saved["user_note"].startswith("I never add to gold in March. See my notes")
    history, failed = ToolBox(db, LATER, True, FactsBuilder()).run(
        "get_recommendation_history", {"subject": None, "limit": 5}
    )
    assert not failed and history["recommendations"][0]["owner_note"] == saved["user_note"]
    assert history["recommendations"][0]["status"] == "rejected"
    bare = made(db, trigger="again")[0]
    assert (
        decide(api, bare, action="reject").json()["recommendation"]["user_note"] is None
    )  # the reason is optional


def test_snoozing_hides_an_item_for_the_days_asked(api: TestClient, db: Session, world) -> None:
    (rec_id,) = made(db)
    for bad in (0, 31, None):
        refused = decide(api, rec_id, action="snooze", days=bad)
        assert refused.status_code == 422 and "1 to 30 days" in refused.json()["detail"]
    ok = decide(api, rec_id, action="snooze", days=3).json()["recommendation"]
    assert ok["status"] == "snoozed" and ok["snoozed_until"].startswith("2024-03-18")
    assert api.get("/api/v1/recommendations").json() == []
    assert [
        r["id"] for r in api.get("/api/v1/recommendations", params={"status": "snoozed"}).json()
    ] == [rec_id]
    expire_due(db, NOW + dt.timedelta(days=4))
    db.commit()
    assert db.get(Recommendation, rec_id).status == "new"  # back on the list


def test_decisions_are_announced_on_the_live_stream(api: TestClient, db: Session, world) -> None:
    (rec_id,) = made(db)
    decide(api, rec_id, action="seen")
    decide(api, rec_id, action="reject")
    events = db.scalars(
        select(AppEvent).where(AppEvent.type == "recommendation").order_by(AppEvent.id)
    ).all()
    assert [(e.payload["id"], e.payload["what"]) for e in events] == [
        (rec_id, "created"),
        (rec_id, "seen"),
        (rec_id, "reject"),
    ]


def test_unknown_items_and_bad_actions_are_explained(api: TestClient, db: Session, world) -> None:
    assert decide(api, 999, action="accept").status_code == 404
    (rec_id,) = made(db)
    assert decide(api, rec_id, action="delete").status_code == 422  # not one of the four
    assert api.get("/api/v1/recommendations/999").status_code == 404
    assert api.get("/api/v1/recommendations", params={"status": "bogus"}).status_code == 422
