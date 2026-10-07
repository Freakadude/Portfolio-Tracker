"""The in-app interview of the strategy helper (ADR 0048).

One talk is an `assistant_session`. Each turn is one metered call (its own `agent_run` row, run
type `strategist`) that answers with a reply, a few suggested answers and, when it has one, the
whole strategy document. A document is checked by the same parser as every strategy; when it has
problems the model is shown them once and asked to fix it before the owner sees anything. The
helper only drafts: nothing is saved as a strategy until the owner does it.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from folio.agent import budget, strategist
from folio.agent.llm import LlmClient, system_blocks
from folio.agent.prompt_files import labels, load_prompt
from folio.agent.runs import finish_run, metered_create, start_run
from folio.db.models_insight import AssistantSession
from folio.settings_schema import AgentSettings
from folio.strategies import service
from folio.strategies.parse import StrategyError

RUN_TYPE = "strategist"
MAX_TURNS = 25  # answers from the model in one talk, repairs not counted
MAX_REPAIRS = 1
MAX_TOKENS = 4000
MAX_CHOICES = 4
OPENING = "Please begin: greet me in one sentence and ask your first question."

TURN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reply", "choices", "draft_yaml"],
    "properties": {
        "reply": {"type": "string"},
        "choices": {"type": "array", "items": {"type": "string"}},
        "draft_yaml": {"type": "string"},
    },
}


class InterviewError(ValueError):
    """The talk cannot go on; the message is for the owner."""


@dataclass(frozen=True)
class Parsed:
    reply: str
    choices: list[str]
    draft_yaml: str


def parse_turn(text: str) -> Parsed:
    """The model's JSON answer; plain text is taken as a reply without choices or a document."""
    try:
        data = json.loads(text)
    except ValueError:
        return Parsed(text.strip(), [], "")
    if not isinstance(data, dict):
        return Parsed(text.strip(), [], "")
    choices = [str(c).strip() for c in data.get("choices") or [] if str(c).strip()]
    return Parsed(
        str(data.get("reply") or "").strip(),
        choices[:MAX_CHOICES],
        str(data.get("draft_yaml") or "").strip(),
    )


def start(db: Session, mode: str, strategy_id: int | None) -> AssistantSession:
    if mode == "revise":
        if strategy_id is None:
            raise InterviewError("Choose the strategy to revise.")
        service.load(db, strategy_id)  # raises StrategyNotFound
    else:
        strategy_id = None
    session = AssistantSession(mode=mode, strategy_id=strategy_id, messages=[])
    db.add(session)
    db.flush()
    return session


def visible(session: AssistantSession) -> list[dict[str, Any]]:
    return [m for m in session.messages if not m.get("hidden")]


def turns_made(session: AssistantSession) -> int:
    return sum(1 for m in session.messages if m["role"] == "assistant" and not m.get("repair"))


def _history(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the model sees: the talk as plain text, its own documents included."""
    return [{"role": m["role"], "content": m["model_text"]} for m in messages]


def _system(db: Session, session: AssistantSession, today: dt.date) -> list[dict[str, Any]]:
    core = load_prompt("strategist")
    manner = load_prompt("strategist_interview")
    context = strategist.context_text(db, today, session.strategy_id)
    return system_blocks(core.text + "\n\n" + manner.text, context)


def _prompt_labels() -> str:
    return labels([load_prompt("strategist"), load_prompt("strategist_interview")])


def _assistant_message(parsed: Parsed, hidden: bool, repair: bool) -> dict[str, Any]:
    text = parsed.reply
    if parsed.draft_yaml:
        text += f"\n\n```yaml\n{parsed.draft_yaml}\n```"
    return {
        "role": "assistant",
        "text": parsed.reply,
        "model_text": text or "(no reply)",
        "choices": parsed.choices,
        "has_draft": bool(parsed.draft_yaml),
        "hidden": hidden,
        "repair": repair,
    }


def _user_message(text: str, hidden: bool = False) -> dict[str, Any]:
    return {"role": "user", "text": text, "model_text": text, "choices": [], "hidden": hidden}


def take_turn(
    db: Session,
    llm: LlmClient,
    cfg: AgentSettings,
    tz: ZoneInfo,
    now: dt.datetime,
    session: AssistantSession,
    user_text: str | None,
) -> None:
    """Answer the owner (or, with no text, open the talk). Raises BudgetExceeded or LlmError
    before anything about the talk is changed; on success the talk, its draft and its cost are
    updated. Does not commit beyond what the metered calls do."""
    if turns_made(session) >= MAX_TURNS:
        raise InterviewError(
            f"This talk has reached its {MAX_TURNS} answers. Save the draft, or start a new talk."
        )
    model = cfg.models[RUN_TYPE]
    system = _system(db, session, now.date())
    working: list[dict[str, Any]] = list(session.messages)
    working.append(_user_message(user_text) if user_text else _user_message(OPENING, hidden=True))
    spent = Decimal(0)
    draft = session.draft_yaml
    problems_left: str | None = None

    for attempt in range(1 + MAX_REPAIRS):
        run = start_run(db, "interview", RUN_TYPE, model, _prompt_labels(), now)
        try:
            reply = metered_create(
                db,
                llm,
                cfg,
                tz,
                now,
                run,
                model=model,
                system=system,
                messages=_history(working),
                max_tokens=MAX_TOKENS,
                output_schema=TURN_SCHEMA,
            )
        except budget.BudgetExceeded as exc:
            finish_run(db, run, now, "budget", str(exc))
            raise
        except Exception as exc:
            finish_run(db, run, now, "failed", str(exc))
            db.commit()
            raise
        finish_run(db, run, now)
        spent += run.cost_eur
        parsed = parse_turn(reply.text)
        if not parsed.draft_yaml:
            working.append(_assistant_message(parsed, hidden=False, repair=attempt > 0))
            break
        try:
            checked = service.read_input(parsed.draft_yaml, None)
        except StrategyError as exc:
            problems_left = "; ".join(
                f"{'line ' + str(p.line) + ': ' if p.line else ''}{p.message}" for p in exc.problems
            )
            if attempt < MAX_REPAIRS:
                working.append(_assistant_message(parsed, hidden=True, repair=attempt > 0))
                working.append(
                    _user_message(
                        "Folio checked the strategy document and found these problems: "
                        f"{problems_left}. Fix them and answer again with the whole document.",
                        hidden=True,
                    )
                )
                continue
            failed = Parsed(
                parsed.reply
                + "\n\nThe strategy document I wrote still had problems, so I have not drafted "
                f"it: {problems_left}. Tell me what to change and I will try again.",
                parsed.choices,
                "",
            )
            working.append(_assistant_message(failed, hidden=False, repair=attempt > 0))
            break
        draft = checked.yaml
        working.append(_assistant_message(parsed, hidden=False, repair=attempt > 0))
        problems_left = None
        break

    session.messages = working
    session.draft_yaml = draft
    session.spent_eur = session.spent_eur + spent
    db.flush()
