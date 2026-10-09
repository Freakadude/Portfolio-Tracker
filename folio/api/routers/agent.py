"""The AI agent's budget, usage and key test (FR-AG-04, FR-AG-09)."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from folio.agent import budget
from folio.agent import outcomes as outcome_rules
from folio.agent.ask import (
    ANALYSE,
    AskError,
    clean_thread,
    position_question,
    queue_ask,
    thread_runs,
)
from folio.agent.llm import LlmClient, LlmError, system_blocks
from folio.agent.runs import finish_run, metered_create, start_run
from folio.agent.trackrecord import track_record
from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.db.base import utcnow
from folio.db.models_insight import AgentRun, Recommendation
from folio.db.models_ledger import Instrument
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


class TrackHorizonOut(BaseModel):
    days: int
    measured: int  # recommendations compared with the price at this horizon
    scored: int  # of those, the ones with a hit or a miss
    hits: int
    hit_rate: Decimal | None
    avg_return: Decimal | None  # price change as a fraction, in the trading currency


class TrackActionOut(BaseModel):
    action_type: str
    scored_type: bool  # only contributions and trims have a direction to judge
    count: int
    by_horizon: list[TrackHorizonOut]


class TrackDecisionOut(BaseModel):
    decision: Literal["accepted", "rejected", "undecided"]
    count: int
    stats: TrackHorizonOut


class TrackRecordOut(BaseModel):
    total: int
    actions: list[TrackActionOut]
    decision_horizon: int
    decisions: list[TrackDecisionOut]
    note: str


TRACK_NOTE = (
    "Price only, in each instrument's trading currency: this judges the call, not the euro "
    "result of what you did. Only contributions (price not lower) and trims (price not higher) "
    "are scored; the other types are measured but never counted. A personal portfolio produces "
    "few recommendations, so read small samples with care."
)


def _horizon(h: outcome_rules.HorizonStats) -> TrackHorizonOut:
    return TrackHorizonOut(
        days=h.days,
        measured=h.measured,
        scored=h.scored,
        hits=h.hits,
        hit_rate=h.hit_rate,
        avg_return=h.avg_return,
    )


@router.get("/track-record", response_model=TrackRecordOut)
def get_track_record(
    _user: UserDep,
    db: DbDep,
    horizon: Annotated[int, Query(description="7, 30 or 90 days")] = 30,
) -> TrackRecordOut:
    """What happened to the agent's recommendations after +7, +30 and +90 days (FR-AG-06)."""
    if horizon not in outcome_rules.HORIZONS:
        raise ApiError(422, "Unknown horizon", "Choose 7, 30 or 90 days.")
    record = track_record(db, horizon)
    return TrackRecordOut(
        total=record.total,
        actions=[
            TrackActionOut(
                action_type=a.action_type,
                scored_type=a.scored_type,
                count=a.count,
                by_horizon=[_horizon(h) for h in a.by_horizon],
            )
            for a in record.actions
        ],
        decision_horizon=record.decision_horizon,
        decisions=[
            TrackDecisionOut(
                decision=d.decision,
                count=d.count,
                stats=_horizon(d.stats),
            )
            for d in record.decisions
        ],
        note=TRACK_NOTE,
    )


# --- questions: "Ask the portfolio" and "Analyse this position" (FR-AG-08, FR-DB-09) ----------


class AskIn(BaseModel):
    question: str | None = Field(default=None, max_length=600)
    instrument_id: int | None = None  # set: analyse this position (the question is optional)
    thread: str | None = Field(default=None, max_length=40)  # a chat in the side panel
    page: str | None = Field(default=None, max_length=120)  # the route the owner is on


class AskQueuedOut(BaseModel):
    run_id: int
    status: str


class AskCitationOut(BaseModel):
    tool: str
    note: str


class AskDataOut(BaseModel):
    tool: str
    note: str
    input: dict[str, Any]
    result: str  # what the tool returned (shortened), the rows the answer rests on


class AskOut(BaseModel):
    id: int
    kind: Literal["ask", "analyse_position"]
    question: str
    instrument_id: int | None
    thread: str | None  # the chat in the side panel this belongs to
    status: str  # queued | running | ok | failed | budget
    answer: str | None  # None until answered, and when the code gate refused the answer
    refused: bool  # the run finished but its answer did not pass the check
    reasons: list[str]  # why it did not pass
    citations: list[AskCitationOut]
    data: list[AskDataOut]
    not_found: str
    error: str | None
    cost_eur: Decimal
    asked_at: datetime
    finished_at: datetime | None
    ai_label: str = "AI-generated, not financial advice."


def _ask_out(run: AgentRun) -> AskOut:
    context = run.context or {}
    output = run.output or {}
    answer = output.get("answer")
    return AskOut(
        id=run.id,
        kind=run.run_type,
        question=str(output.get("question") or context.get("question") or ""),
        instrument_id=context.get("instrument_id"),
        thread=context.get("thread"),
        status=run.status,
        answer=answer if isinstance(answer, str) else None,
        refused=run.status == "ok" and not output.get("accepted", False),
        reasons=[str(r) for r in output.get("reasons") or []],
        citations=[AskCitationOut(**c) for c in output.get("citations") or []],
        data=[AskDataOut(**d) for d in output.get("data") or []],
        not_found=str(output.get("not_found") or ""),
        error=run.error,
        cost_eur=run.cost_eur,
        asked_at=run.started_at,
        finished_at=run.finished_at,
    )


@router.post("/ask", response_model=AskQueuedOut, status_code=202)
def ask(body: AskIn, request: Request, _user: UserDep, db: DbDep) -> AskQueuedOut:
    """Put a question to the agent. It reads the portfolio with its tools and answers; it never
    changes anything. The worker answers in the background: poll GET /agent/ask/{run_id}."""
    cfg = budget.agent_settings(db)
    if not cfg.enabled:
        raise ApiError(409, "Agent is off", "The AI agent is switched off in Settings, Agent.")
    if not key_is_set(db, request):
        raise ApiError(409, "No API key", "Add your Anthropic API key in Settings, Agent.")
    instrument = None
    if body.instrument_id is not None:
        instrument = db.get(Instrument, body.instrument_id)
        if instrument is None or instrument.deleted_at is not None:
            raise ApiError(404, "Not found", "That instrument does not exist.")
    question = body.question if body.question and body.question.strip() else None
    if question is None:
        if instrument is None:
            raise ApiError(422, "Question needed", "Write the question in a few words.")
        question = position_question(instrument)
    try:
        run = queue_ask(db, cfg, question, instrument, utcnow(), body.thread, body.page)
    except AskError as exc:
        raise ApiError(422, "Cannot ask that", str(exc)) from exc
    enqueue(db, "agent_ask", {"run_id": run.id})
    return AskQueuedOut(run_id=run.id, status=run.status)


@router.get("/ask", response_model=list[AskOut])
def recent_questions(
    _user: UserDep,
    db: DbDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    instrument_id: int | None = None,
) -> list[AskOut]:
    """The latest questions with their answers, newest first."""
    rows = db.scalars(
        select(AgentRun)
        .where(AgentRun.run_type.in_(("ask", ANALYSE)))
        .order_by(AgentRun.id.desc())
        .limit(200 if instrument_id is not None else limit)
    ).all()
    if instrument_id is not None:
        rows = [r for r in rows if (r.context or {}).get("instrument_id") == instrument_id][:limit]
    return [_ask_out(r) for r in rows]


@router.get("/chat/{thread}", response_model=list[AskOut])
def chat_thread(thread: str, _user: UserDep, db: DbDep) -> list[AskOut]:
    """The turns of one chat in the side panel, oldest first."""
    try:
        return [_ask_out(r) for r in thread_runs(db, clean_thread(thread))]
    except AskError as exc:
        raise ApiError(422, "Cannot read that chat", str(exc)) from exc


@router.get("/ask/{run_id}", response_model=AskOut)
def get_question(run_id: int, _user: UserDep, db: DbDep) -> AskOut:
    run = db.get(AgentRun, run_id)
    if run is None or run.run_type not in ("ask", ANALYSE):
        raise ApiError(404, "Not found", "That question does not exist.")
    return _ask_out(run)
