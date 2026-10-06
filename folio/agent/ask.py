"""Questions to the agent: "Ask the portfolio" and "Analyse this position" (FR-AG-08, FR-DB-09).

It only reads. The run uses the same read-only tools, privacy mode and budget guard as every
other run, in two steps: an investigation that gathers facts with the tools, and a separate call
that writes the answer in a fixed structure. The code gate (`answers.py`) then decides whether it
is shown: every figure in it must be a number a tool returned and every citation a tool the run
called. No recommendation and no draft transaction is ever made here.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from folio.agent import budget
from folio.agent.answers import check_answer, data_used
from folio.agent.context import build_pack
from folio.agent.facts import FactsBuilder
from folio.agent.llm import LlmClient, LlmError, system_blocks
from folio.agent.prompt_files import labels, load_prompt
from folio.agent.run import COMPOSE_TOKENS, _investigate
from folio.agent.runs import finish_run, metered_create
from folio.agent.schema import ANSWER_SCHEMA
from folio.agent.tools import ToolBox
from folio.db.models_insight import AgentRun
from folio.db.models_ledger import Instrument
from folio.settings_schema import AgentSettings

QUESTION_MIN = 3
QUESTION_MAX = 500
ASK = "ask"
ANALYSE = "analyse_position"


class AskError(ValueError):
    """The question cannot be put; the message is for the owner."""


@dataclass
class AskOutcome:
    run_id: int
    status: str  # ok | failed | budget
    accepted: bool = False
    reasons: list[str] = field(default_factory=list)
    cost_eur: Decimal = Decimal(0)
    error: str | None = None


def clean_question(text: str) -> str:
    question = " ".join(text.split())
    if len(question) < QUESTION_MIN:
        raise AskError("Write the question in a few words.")
    if len(question) > QUESTION_MAX:
        raise AskError(f"Keep the question to {QUESTION_MAX} characters.")
    return question


def position_question(instrument: Instrument) -> str:
    return (
        f"Analyse my position in {instrument.name}: what I hold and what it cost, how it has "
        "done, how much of the portfolio it is and where my strategy puts it, what open signals "
        "and recent news touch it, and what the strategy's principles say about it."
    )[:QUESTION_MAX]


def queue_ask(
    db: Session,
    cfg: AgentSettings,
    question: str,
    instrument: Instrument | None,
    now: dt.datetime,
) -> AgentRun:
    """Make the run row the owner will wait on; the worker picks it up by its id."""
    kind = ANALYSE if instrument is not None else ASK
    run = AgentRun(
        trigger=kind,
        run_type=kind,
        model=cfg.models[kind],
        started_at=now,
        status="queued",
        context={
            "question": clean_question(question),
            "instrument_id": None if instrument is None else instrument.id,
        },
    )
    db.add(run)
    db.flush()
    return run


def run_ask(db: Session, llm: LlmClient, now: dt.datetime, run: AgentRun) -> AskOutcome:
    cfg = budget.agent_settings(db)
    tz = budget.timezone_of(db)
    model = cfg.models[run.run_type]
    prompts = [load_prompt("system"), load_prompt("ask_investigate"), load_prompt("ask_answer")]
    asked = dict(run.context or {})
    question = str(asked.get("question") or "")
    run.model, run.prompt_version = model, labels(prompts)[:200]
    run.status, run.started_at = "running", now
    db.commit()
    outcome = AskOutcome(run.id, "ok")
    facts = FactsBuilder()
    tools = ToolBox(db, now, cfg.privacy_mode, facts)
    tool_calls: list[dict[str, Any]] = []
    try:
        focus = None
        instrument_id = asked.get("instrument_id")
        if instrument_id is not None:
            instrument = db.get(Instrument, int(instrument_id))
            focus = (
                None
                if instrument is None
                else f"Position: {instrument.name} (instrument id {instrument.id})"
            )
        pack_text, pack = build_pack(tools, run.run_type, "ask", focus, now)
        run.context = {**asked, **pack}
        db.commit()
        findings = _investigate(
            db, llm, cfg, tz, now, run, model, prompts[:2], tools, facts,
            f"Question from the owner: {question}\n\n{pack_text}", tool_calls,
        )  # fmt: skip
        run.findings, run.tool_calls = findings, tool_calls
        called = sorted({str(c["name"]) for c in tool_calls})
        reply = metered_create(
            db, llm, cfg, tz, now, run, model=model,
            system=system_blocks(prompts[0].text, prompts[2].text),
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Question from the owner: {question}\n\nFindings of the investigation:\n"
                        f"{findings}\n\nTools used in the investigation: "
                        f"{', '.join(called) or 'none'}."
                    ),
                }
            ],
            max_tokens=COMPOSE_TOKENS, output_schema=ANSWER_SCHEMA,
        )  # fmt: skip
        try:
            data = json.loads(reply.text)
        except ValueError as exc:
            raise ValueError(f"the answer is not JSON ({exc})") from exc
        verdict = check_answer(data, facts.freeze())
        run.output = {
            "kind": run.run_type,
            "question": question,
            "accepted": verdict.accepted,
            "reasons": list(verdict.reasons),
            "answer": None if verdict.answer is None else verdict.answer.text,
            "citations": []
            if verdict.answer is None
            else [{"tool": c.tool, "note": c.note} for c in verdict.answer.citations],
            "not_found": "" if verdict.answer is None else verdict.answer.not_found,
            "data": []
            if verdict.answer is None
            else data_used(verdict.answer.citations, tool_calls),
            "raw": reply.text,
        }
        run.digest = "" if verdict.answer is None else verdict.answer.text[:500]
        outcome.accepted, outcome.reasons = verdict.accepted, list(verdict.reasons)
        finish_run(db, run, now)
    except budget.BudgetExceeded as exc:
        run.tool_calls = tool_calls
        finish_run(db, run, now, "budget", str(exc))
        budget.stop_notice(db, exc, now, tz, run.run_type)
        outcome.status, outcome.error = "budget", str(exc)
    except LlmError as exc:
        run.tool_calls = tool_calls
        finish_run(db, run, now, "failed", str(exc))
        outcome.status, outcome.error = "failed", str(exc)
    except (ValueError, KeyError) as exc:  # an answer that could not be read
        run.tool_calls = tool_calls
        finish_run(db, run, now, "failed", f"The answer could not be read: {exc}")
        outcome.status, outcome.error = "failed", str(exc)
    outcome.cost_eur = run.cost_eur
    db.commit()
    return outcome
