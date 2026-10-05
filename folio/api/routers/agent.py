"""The AI agent's budget, usage and key test (FR-AG-04, FR-AG-09)."""

from decimal import Decimal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from folio.agent import budget
from folio.agent.llm import LlmClient, LlmError, system_blocks
from folio.agent.runs import finish_run, metered_create, start_run
from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.db.base import utcnow
from folio.security.secrets import SecretStore

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentBudgetOut(BaseModel):
    month: str
    enabled: bool
    key_set: bool
    spent_eur: Decimal
    budget_eur: Decimal
    remaining_eur: Decimal
    news_spent_eur: Decimal
    news_share_eur: Decimal
    runs_this_month: int
    runs_today: int
    daily_run_cap: int
    paused: bool  # the budget is used up


class AgentKeyTestOut(BaseModel):
    ok: bool
    model: str
    reply: str
    cost_eur: Decimal


def key_is_set(db: DbDep, request: Request) -> bool:
    store = SecretStore(db, request.app.state.settings.require_secret_key())
    return store.has("agent.anthropic_api_key")


@router.get("/usage", response_model=AgentBudgetOut)
def usage(request: Request, _user: UserDep, db: DbDep) -> AgentBudgetOut:
    """What the agent has cost this month against the budget (spec section 11, cost control)."""
    cfg = budget.agent_settings(db)
    state = budget.standing(db, cfg, utcnow(), budget.timezone_of(db))
    return AgentBudgetOut(
        month=state.month,
        enabled=cfg.enabled,
        key_set=key_is_set(db, request),
        spent_eur=state.spent_eur,
        budget_eur=state.budget_eur,
        remaining_eur=state.remaining_eur,
        news_spent_eur=state.news_spent_eur,
        news_share_eur=state.news_share_eur,
        runs_this_month=state.runs_this_month,
        runs_today=state.runs_today,
        daily_run_cap=state.daily_run_cap,
        paused=state.spent_eur >= state.budget_eur,
    )


@router.post("/test", response_model=AgentKeyTestOut)
def test_key(request: Request, _user: UserDep, db: DbDep) -> AgentKeyTestOut:
    """A tiny call that proves the saved key works and shows what it costs."""
    cfg = budget.agent_settings(db)
    state = request.app.state
    store = SecretStore(db, state.settings.require_secret_key())
    key = store.get("agent.anthropic_api_key")
    if not key:
        raise ApiError(409, "No API key", "Save your Anthropic API key first.")
    model = cfg.models["news_triage"]  # the cheapest model
    now = utcnow()
    tz = budget.timezone_of(db)
    llm = LlmClient(key, transport=getattr(state, "llm_transport", None))
    run = start_run(db, "test", "test", model, "", now)
    try:
        reply = metered_create(
            db,
            llm,
            cfg,
            tz,
            now,
            run,
            model=model,
            system=system_blocks("You are a connection test. Answer with one word."),
            messages=[{"role": "user", "content": "Say ok."}],
            max_tokens=16,
        )
    except budget.BudgetExceeded as exc:
        finish_run(db, run, now, "budget", str(exc))
        raise ApiError(409, "Budget", str(exc)) from exc
    except LlmError as exc:
        finish_run(db, run, now, "failed", str(exc))
        db.commit()
        raise ApiError(502 if exc.kind != "auth" else 422, "The test failed", str(exc)) from exc
    finish_run(db, run, now)
    return AgentKeyTestOut(
        ok=True, model=reply.model, reply=reply.text.strip()[:60], cost_eur=run.cost_eur
    )
