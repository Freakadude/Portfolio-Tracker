"""The AI agent's budget, usage and key test (FR-AG-04, FR-AG-09)."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

from folio.agent import budget
from folio.agent.llm import LlmClient, LlmError, system_blocks
from folio.agent.runs import finish_run, metered_create, start_run
from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.db.base import utcnow
from folio.db.models_insight import AgentRun, Recommendation
from folio.jobs.requests import enqueue
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


# --- runs and their traces (FR-AG-01, spec section 11) ---------------------------------


class AgentRunIn(BaseModel):
    run_type: Literal["daily_review", "on_demand"] = "on_demand"
    question: str | None = None  # for an on-demand run: what the owner wants looked at


class AgentRunOut(BaseModel):
    id: int
    trigger: str
    run_type: str
    model: str
    prompt_version: str
    status: str
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    web_searches: int
    cost_eur: Decimal
    digest: str
    recommendations: int  # made and shown
    refused: int  # refused by the code gate, never shown as advice


class AgentRecOut(BaseModel):
    id: int
    action_type: str
    severity: str
    subjects: list[str]
    title: str
    status: str
    refused_reason: str | None


class AgentRunDetailOut(AgentRunOut):
    context: dict[str, Any]
    tool_calls: list[dict[str, Any]]
    findings: str
    output: dict[str, Any]
    items: list[AgentRecOut]


def _run_out(db: DbDep, run: AgentRun) -> AgentRunOut:
    rows = list(db.scalars(select(Recommendation).where(Recommendation.run_id == run.id)))
    return AgentRunOut(
        id=run.id,
        trigger=run.trigger,
        run_type=run.run_type,
        model=run.model,
        prompt_version=run.prompt_version,
        status=run.status,
        error=run.error,
        started_at=run.started_at,
        finished_at=run.finished_at,
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        cache_read_tokens=run.cache_read_tokens,
        cache_write_tokens=run.cache_write_tokens,
        web_searches=run.web_searches,
        cost_eur=run.cost_eur,
        digest=run.digest,
        recommendations=sum(1 for r in rows if r.status != "refused"),
        refused=sum(1 for r in rows if r.status == "refused"),
    )


@router.get("/runs", response_model=list[AgentRunOut])
def list_runs(
    _user: UserDep, db: DbDep, limit: Annotated[int, Query(ge=1, le=200)] = 30
) -> list[AgentRunOut]:
    """The agent's runs, newest first, with what each cost (shown on the System page)."""
    runs = db.scalars(select(AgentRun).order_by(AgentRun.id.desc()).limit(limit))
    return [_run_out(db, r) for r in runs]


@router.get("/runs/{run_id}", response_model=AgentRunDetailOut)
def one_run(run_id: int, _user: UserDep, db: DbDep) -> AgentRunDetailOut:
    """The full trace of a run: context pack, tool calls, findings, the model's answer and the
    verdict on each recommendation, refused ones with their reasons."""
    run = db.get(AgentRun, run_id)
    if run is None:
        raise ApiError(404, "Not found", "That run does not exist.")
    items = db.scalars(
        select(Recommendation).where(Recommendation.run_id == run_id).order_by(Recommendation.id)
    )
    base = _run_out(db, run).model_dump()
    return AgentRunDetailOut(
        **base,
        context=dict(run.context or {}),
        tool_calls=list(run.tool_calls or []),
        findings=run.findings,
        output=dict(run.output or {}),
        items=[
            AgentRecOut(
                id=r.id,
                action_type=r.action_type,
                severity=r.severity,
                subjects=list(r.subjects or []),
                title=r.title,
                status=r.status,
                refused_reason=r.refused_reason,
            )
            for r in items
        ],
    )


@router.post("/runs", status_code=202)
def start_run_now(body: AgentRunIn, _user: UserDep, db: DbDep) -> dict[str, str]:
    """Ask the worker for a run now: "Run a review now", or a question about the portfolio."""
    if not budget.agent_settings(db).enabled:
        raise ApiError(409, "Agent is off", "The AI agent is switched off in Settings, Agent.")
    enqueue(db, "agent_run", {"run_type": body.run_type, "question": body.question})
    return {"status": "queued"}
