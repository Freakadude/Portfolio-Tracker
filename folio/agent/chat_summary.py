"""Summarising chosen chats into short notes about the owner (ADR 0048).

One cheap-model call per chat, each recorded as its own `agent_run` (run type `chat_summary`)
and each checked against the monthly budget before it is made. The summaries are returned to the
owner to read and edit; nothing is saved as a note here.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from folio.agent import budget
from folio.agent.chat_export import Chat, transcript
from folio.agent.cost import estimate_input_tokens, to_eur, worst_case_usd
from folio.agent.llm import LlmClient, LlmError, system_blocks
from folio.agent.prompt_files import load_prompt
from folio.agent.runs import finish_run, metered_create, start_run
from folio.settings_schema import AgentSettings

RUN_TYPE = "chat_summary"
MAX_CHATS = 8  # per request, so one request stays short
MAX_OUTPUT_TOKENS = 400
NOTHING = "NOTHING"


@dataclass(frozen=True)
class Estimate:
    chats: int
    tokens: int
    cost_eur: Decimal  # the most it can cost
    remaining_eur: Decimal
    fits: bool
    model: str


@dataclass(frozen=True)
class Summary:
    id: str
    title: str
    text: str | None  # None: the chat held nothing about the owner's own investing
    cost_eur: Decimal


@dataclass(frozen=True)
class Failure:
    id: str
    title: str
    reason: str


def model_for(cfg: AgentSettings) -> str:
    return cfg.models["news_triage"]  # the cheapest model


def estimate(
    db: Session, cfg: AgentSettings, tz: ZoneInfo, now: dt.datetime, chats: list[Chat]
) -> Estimate:
    """What summarising these chats can cost at most, against what is left of the month."""
    model = model_for(cfg)
    price = budget.price_for(cfg, model)
    tokens = sum(estimate_input_tokens(len(transcript(c))) for c in chats)
    worst = worst_case_usd(price, tokens, MAX_OUTPUT_TOKENS * len(chats), 0, Decimal(0))
    cost = to_eur(worst, budget.usd_per_eur(db, cfg, now.date()))
    remaining = budget.standing(db, cfg, now, tz).remaining_eur
    return Estimate(len(chats), tokens, cost, remaining, cost <= remaining, model)


def summarise(
    db: Session,
    llm: LlmClient,
    cfg: AgentSettings,
    tz: ZoneInfo,
    now: dt.datetime,
    chats: list[Chat],
) -> tuple[list[Summary], list[Failure], str | None]:
    """Summaries of the chats, those that failed, and why the work stopped early (the budget)."""
    prompt = load_prompt("chat_summary")
    model = model_for(cfg)
    done: list[Summary] = []
    failed: list[Failure] = []
    for chat in chats:
        run = start_run(db, "chat_import", RUN_TYPE, model, prompt.label, now)
        try:
            reply = metered_create(
                db,
                llm,
                cfg,
                tz,
                now,
                run,
                model=model,
                system=system_blocks(prompt.text),
                messages=[
                    {
                        "role": "user",
                        "content": f"The chat (title: {chat.title}):\n\n<chat>\n"
                        f"{transcript(chat)}\n</chat>",
                    }
                ],
                max_tokens=MAX_OUTPUT_TOKENS,
            )
        except budget.BudgetExceeded as exc:
            finish_run(db, run, now, "budget", str(exc))
            db.commit()
            return done, failed, str(exc)
        except LlmError as exc:
            finish_run(db, run, now, "failed", str(exc))
            db.commit()
            failed.append(Failure(chat.id, chat.title, str(exc)))
            continue
        finish_run(db, run, now)
        text = reply.text.strip()
        done.append(
            Summary(
                chat.id, chat.title, None if text == NOTHING or not text else text, run.cost_eur
            )
        )
        db.commit()
    return done, failed, None
