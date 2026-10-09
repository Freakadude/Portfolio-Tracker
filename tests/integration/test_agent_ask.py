# ruff: noqa: F811  (the fixtures are imported from other test modules and used as parameters)
"""Ask the portfolio and Analyse this position (FR-AG-08, FR-DB-09): the run only reads, the
answer is shown only if the code gate passes it, and nothing is ever recommended or drafted."""

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from folio.agent import budget
from folio.agent.ask import AskError, clean_question, queue_ask, run_ask
from folio.agent.tools import TOOL_DEFS
from folio.config import Settings
from folio.db.models_insight import Calculation, Recommendation
from folio.db.models_ledger import Instrument, JobRequest, LedgerTransaction
from folio.db.models_strategy import Notification
from folio.jobs.agent import agent_ask_job
from tests.agent_helpers import ScriptedLlm, message, text, tool_use
from tests.conftest import PASSWORD, USERNAME
from tests.integration.test_agent_run import NOW, job_ctx, settings_save, world  # noqa: F401
from tests.integration.test_news_pipeline import book, db  # noqa: F401

D = Decimal
KEY = "sk-ant-api03-" + "k" * 40


class AskBrain:
    """A model that looks at the open signals, then answers as told."""

    def __init__(
        self,
        answer: str = "Gold is 20.0 pp under its target.",
        citations: list[dict[str, str]] | None = None,
        not_found: str = "",
        calls: list[tuple[str, dict[str, Any]]] | None = None,
    ) -> None:
        self.answer, self.not_found = answer, not_found
        self.citations = (
            citations
            if citations is not None
            else [{"tool": "get_signals", "note": "the open drift signal"}]
        )
        self.calls = (
            calls if calls is not None else [("get_signals", {"state": "open", "since": None})]
        )

    def __call__(self, body: dict[str, Any]) -> dict[str, Any]:
        model = body["model"]
        if "output_config" in body:
            payload = {
                "answer": self.answer,
                "citations": self.citations,
                "not_found": self.not_found,
            }
            return message(
                text(json.dumps(payload)), model=model, input_tokens=700, output_tokens=120
            )
        content = body["messages"][-1]["content"]
        if isinstance(content, list) and content[0].get("type") == "tool_result":
            return message(text("Gold is under its target (signal 1)."), model=model)
        blocks = [tool_use(n, f"toolu_{i}", **a) for i, (n, a) in enumerate(self.calls)]
        return message(*blocks, stop="tool_use", model=model, input_tokens=1500, output_tokens=100)


def asked(
    db: Session, llm: ScriptedLlm, question: str = "How far is gold from its target?", **kw: Any
):  # type: ignore[no-untyped-def]
    cfg = budget.agent_settings(db)
    run = queue_ask(db, cfg, question, kw.get("instrument"), NOW)
    db.commit()
    outcome = run_ask(db, llm.client(), NOW, run)
    db.refresh(run)
    return run, outcome


# --- the run --------------------------------------------------------------------------------------


def test_a_question_is_investigated_answered_checked_and_shown_with_its_data(
    db: Session, world
) -> None:
    llm = ScriptedLlm(handler=AskBrain())
    run, outcome = asked(db, llm)
    assert (outcome.status, outcome.accepted, outcome.reasons) == ("ok", True, [])
    investigate = [r for r in llm.requests if "output_config" not in r]
    answer = [r for r in llm.requests if "output_config" in r]
    assert len(investigate) == 2 and len(answer) == 1 and llm.requests[-1] is answer[0]
    assert {t["name"] for t in investigate[0]["tools"]} == {t["name"] for t in TOOL_DEFS}
    assert "tools" not in answer[0] and answer[0]["model"] == "claude-sonnet-5-5"
    assert "Question from the owner: How far is gold from its target?" in str(
        investigate[0]["messages"][0]["content"]
    )
    assert answer[0]["output_config"]["format"]["schema"]["required"] == [
        "answer",
        "citations",
        "not_found",
    ]

    assert (run.run_type, run.status, run.cost_eur > 0) == ("ask", "ok", True)
    assert run.prompt_version.count("@") == 3 and "ask_answer@2+" in run.prompt_version
    assert run.output["answer"] == "Gold is 20.0 pp under its target."
    (used,) = run.output["data"]
    assert used["tool"] == "get_signals" and used["input"] == {"state": "open", "since": None}
    assert "gold_hedge is 20.0 pp under its target" in used["result"]  # the row it rests on
    assert run.digest.startswith("Gold is 20.0 pp")

    # it only reads: no recommendation, no draft, no calculation, nothing in the inbox
    assert db.scalars(select(Recommendation)).all() == []
    assert db.scalars(select(Calculation)).all() == []
    assert (
        db.scalars(select(LedgerTransaction).where(LedgerTransaction.status == "draft")).all() == []
    )
    assert db.scalars(select(Notification).where(Notification.source == "agent")).all() == []


def test_an_invented_number_means_no_answer_is_shown(db: Session, world) -> None:
    run, outcome = asked(db, ScriptedLlm(handler=AskBrain(answer="Gold is 35.5 pp under target.")))
    assert (outcome.status, outcome.accepted) == ("ok", False)
    assert outcome.reasons == ["a figure in the answer was not in the data this run read: 35.5 pp"]
    assert run.output["answer"] is None and run.output["accepted"] is False
    assert run.output["data"] == [] and "35.5 pp" in run.output["raw"]  # kept in the trace only
    assert run.digest == ""


def test_citing_a_tool_the_run_did_not_use_means_no_answer_is_shown(db: Session, world) -> None:
    brain = AskBrain(citations=[{"tool": "run_calculator", "note": "an order"}])
    run, outcome = asked(db, ScriptedLlm(handler=brain))
    assert not outcome.accepted
    assert outcome.reasons == ["it cites run_calculator, which this run did not use"]


def test_privacy_mode_keeps_euro_amounts_out_of_answers(db: Session, world) -> None:
    llm = ScriptedLlm(handler=AskBrain(answer="You hold € 7,654.32 of gold."))
    _, outcome = asked(db, llm)
    assert not outcome.accepted and "€ 7,654.32" in outcome.reasons[0]


def test_a_used_up_budget_stops_the_question_before_any_call_is_made(db: Session, world) -> None:
    settings_save(db, monthly_budget_eur=D("0"))
    llm = ScriptedLlm(handler=AskBrain())
    run, outcome = asked(db, llm)
    assert (outcome.status, run.status) == ("budget", "budget")
    assert llm.requests == [] and run.error
    assert any(
        "budget" in n.title.lower() for n in db.scalars(select(Notification)).all()
    )  # the one notice of the month


def test_a_position_is_analysed_with_its_name_in_the_focus(db: Session, world) -> None:
    gold = db.scalar(select(Instrument).where(Instrument.name == "Gold ETC"))
    llm = ScriptedLlm(handler=AskBrain())
    cfg = budget.agent_settings(db)
    run = queue_ask(db, cfg, "Analyse it", gold, NOW)
    db.commit()
    run_ask(db, llm.client(), NOW, run)
    db.refresh(run)
    assert run.run_type == "analyse_position" and run.context["instrument_id"] == gold.id
    assert "Position: Gold ETC" in str(llm.requests[0]["messages"][0]["content"])
    assert run.context["question"] == "Analyse it" and run.output["accepted"] is True


def test_questions_are_cleaned_and_bounded() -> None:
    assert clean_question("  How   is\n gold doing? ") == "How is gold doing?"
    with pytest.raises(AskError, match="few words"):
        clean_question("  ?")
    with pytest.raises(AskError, match="500"):
        clean_question("x" * 501)


# --- the API and the worker -----------------------------------------------------------------------


@pytest.fixture
def api(make_client: Callable[..., TestClient], owner: None) -> TestClient:
    c = make_client()
    c.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return c


def test_a_question_waits_for_the_worker_and_then_has_its_answer(
    api: TestClient, db: Session, world, settings: Settings
) -> None:
    assert api.put("/api/v1/settings/agent", json={"anthropic_api_key": KEY}).status_code == 200
    queued = api.post("/api/v1/agent/ask", json={"question": "How far is gold from its target?"})
    assert queued.status_code == 202, queued.text
    run_id = queued.json()["run_id"]
    waiting = api.get(f"/api/v1/agent/ask/{run_id}").json()
    assert (waiting["status"], waiting["answer"], waiting["kind"]) == ("queued", None, "ask")
    assert waiting["question"] == "How far is gold from its target?" and waiting["refused"] is False
    db.expire_all()
    assert (
        db.scalar(select(func.count()).select_from(JobRequest).where(JobRequest.job == "agent_ask"))
        == 1
    )

    llm = ScriptedLlm(handler=AskBrain())
    result = agent_ask_job(job_ctx(settings, llm), run_id)
    assert result.status == "ok" and "answered" in result.log
    again = agent_ask_job(job_ctx(settings, llm), run_id)  # not waiting any more
    assert "not waiting" in again.log

    done = api.get(f"/api/v1/agent/ask/{run_id}").json()
    assert done["status"] == "ok" and done["answer"] == "Gold is 20.0 pp under its target."
    assert done["ai_label"] == "AI-generated, not financial advice."
    assert done["citations"] == [{"tool": "get_signals", "note": "the open drift signal"}]
    assert done["data"][0]["tool"] == "get_signals" and "20.0 pp" in done["data"][0]["result"]
    assert done["refused"] is False and float(done["cost_eur"]) > 0

    listed = api.get("/api/v1/agent/ask").json()
    assert [q["id"] for q in listed] == [run_id]


def test_a_refused_answer_is_reported_as_refused_without_its_text(
    api: TestClient, db: Session, world, settings: Settings
) -> None:
    api.put("/api/v1/settings/agent", json={"anthropic_api_key": KEY})
    run_id = api.post("/api/v1/agent/ask", json={"question": "Tell me about gold"}).json()["run_id"]
    agent_ask_job(
        job_ctx(settings, ScriptedLlm(handler=AskBrain(answer="Gold is 99 pp under."))), run_id
    )
    body = api.get(f"/api/v1/agent/ask/{run_id}").json()
    assert (body["status"], body["answer"], body["refused"]) == ("ok", None, True)
    assert body["reasons"] and "99 pp" in body["reasons"][0]


def test_the_worker_without_a_client_marks_the_question_failed(
    api: TestClient, db: Session, world, settings: Settings
) -> None:
    api.put("/api/v1/settings/agent", json={"anthropic_api_key": KEY})
    run_id = api.post("/api/v1/agent/ask", json={"question": "Tell me about gold"}).json()["run_id"]
    result = agent_ask_job(job_ctx(settings, None), run_id)
    assert "switched off or has no API key" in result.log
    body = api.get(f"/api/v1/agent/ask/{run_id}").json()
    assert body["status"] == "failed" and "no API key" in body["error"]


def test_asking_needs_the_agent_a_key_and_a_real_question(
    api: TestClient, db: Session, world
) -> None:
    assert api.post("/api/v1/agent/ask", json={"question": "How is gold?"}).status_code == 409
    api.put("/api/v1/settings/agent", json={"anthropic_api_key": KEY})
    assert api.post("/api/v1/agent/ask", json={}).status_code == 422
    assert api.post("/api/v1/agent/ask", json={"question": "??"}).status_code == 422
    assert api.post("/api/v1/agent/ask", json={"question": "x" * 501}).status_code == 422
    missing = api.post("/api/v1/agent/ask", json={"instrument_id": 9999})
    assert missing.status_code == 404
    api.put("/api/v1/settings/agent", json={"enabled": False})
    off = api.post("/api/v1/agent/ask", json={"question": "How is gold?"})
    assert off.status_code == 409 and "switched off" in off.json()["detail"]


def test_analyse_this_position_asks_with_a_prepared_question(
    api: TestClient, db: Session, world
) -> None:
    api.put("/api/v1/settings/agent", json={"anthropic_api_key": KEY})
    gold = db.scalar(select(Instrument).where(Instrument.name == "Gold ETC"))
    queued = api.post("/api/v1/agent/ask", json={"instrument_id": gold.id}).json()
    body = api.get(f"/api/v1/agent/ask/{queued['run_id']}").json()
    assert body["kind"] == "analyse_position" and body["instrument_id"] == gold.id
    assert body["question"].startswith("Analyse my position in Gold ETC")
    other = api.get(f"/api/v1/agent/ask?instrument_id={gold.id + 1}").json()
    assert other == []
    assert [q["id"] for q in api.get(f"/api/v1/agent/ask?instrument_id={gold.id}").json()] == [
        queued["run_id"]
    ]
    assert api.get("/api/v1/agent/ask/99999").status_code == 404


def test_asking_needs_a_login(client: TestClient, owner: None) -> None:
    assert client.post("/api/v1/agent/ask", json={"question": "How is gold?"}).status_code == 401
    assert client.get("/api/v1/agent/ask").status_code == 401
