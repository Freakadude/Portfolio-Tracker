"""Runs and metered calls (FR-AG-04).

A run is one `agent_run` row, the full trace of a piece of work: which prompts, which model,
what it cost. Every call to the LLM goes through `metered_create`, which refuses it when the
budget would be passed, and records its cost after. The database is committed before the call so
a slow answer never holds the write lock.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from folio.agent import budget
from folio.agent.cost import estimate_input_tokens, worst_case_usd
from folio.agent.llm import LlmClient, LlmError, Reply
from folio.db.models_insight import AgentRun
from folio.settings_schema import AgentSettings

ZERO = Decimal(0)


def start_run(
    db: Session, trigger: str, run_type: str, model: str, prompts: str, now: dt.datetime
) -> AgentRun:
    run = AgentRun(
        trigger=trigger[:60],
        run_type=run_type,
        model=model,
        prompt_version=prompts[:200],
        started_at=now,
        status="running",
    )
    db.add(run)
    db.flush()
    return run


def finish_run(
    db: Session, run: AgentRun, now: dt.datetime, status: str = "ok", error: str | None = None
) -> None:
    run.status, run.finished_at, run.error = status, now, error
    db.flush()


def metered_create(
    db: Session,
    llm: LlmClient,
    cfg: AgentSettings,
    tz: ZoneInfo,
    now: dt.datetime,
    run: AgentRun,
    *,
    model: str,
    system: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    max_tokens: int,
    tools: list[dict[str, Any]] | None = None,
    output_schema: dict[str, Any] | None = None,
    max_searches: int = 0,
    new_run: bool = False,
) -> Reply:
    """One call to the LLM, within the budget. Raises BudgetExceeded before the call when it
    does not fit, and LlmError when the call fails."""
    used = run.input_tokens + run.output_tokens + run.cache_read_tokens + run.cache_write_tokens
    if used >= cfg.per_run_token_cap:
        raise budget.BudgetExceeded(
            "run_tokens",
            f"This run used its limit of {cfg.per_run_token_cap} tokens and was stopped.",
        )
    sized = len(json.dumps(system)) + len(json.dumps(messages)) + len(json.dumps(tools or []))
    worst = worst_case_usd(
        budget.price_for(cfg, model),
        estimate_input_tokens(sized),
        max_tokens,
        max_searches,
        cfg.web_search_usd_per_1000,
    )
    budget.check_call(
        db,
        cfg,
        now,
        tz,
        run_type=run.run_type,
        worst_case_usd_amount=worst,
        new_run=new_run,
        run_id=run.id,
    )
    db.commit()  # no write lock is held while the model thinks
    reply = llm.create(
        model=model,
        system=system,
        messages=messages,
        max_tokens=max_tokens,
        tools=tools,
        output_schema=output_schema,
    )
    budget.charge(db, run, cfg, reply.usage, model, now.date())
    db.commit()
    return reply


__all__ = ["LlmError", "finish_run", "metered_create", "start_run"]
