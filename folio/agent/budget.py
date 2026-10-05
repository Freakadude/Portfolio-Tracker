"""Budget enforcement and cost tracking for every LLM call (FR-AG-04).

Every call, agent run or news step, is recorded in `agent_run` with its tokens and its cost in
euro. Before a call, the worst case it could cost (all input at full price, the whole output
allowance, every search) is added to what the month has already cost; if that would pass the
monthly budget the call is not made. News triage may only use its own share of the budget, so it
can never leave the agent nothing. A run-per-day cap keeps a loop from running away.

The month is the calendar month in the owner's timezone. When a call is refused, one notice goes
to the inbox for that month or day (critical if a critical signal is open, since the agent then
cannot look at it).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.agent.cost import Usage, cost_usd, to_eur
from folio.db.models_insight import AgentRun
from folio.db.models_strategy import Notification, Signal
from folio.marketdata.fx import FxService, FxUnavailable
from folio.notify.service import notify
from folio.settings_schema import AgentSettings, GeneralSettings, ModelPrice
from folio.settings_store import load_section

AGENT_RUN_TYPES = (
    "daily_review",
    "event_run",
    "weekly_review",
    "contribution_plan",
    "on_demand",
    "event_brief",
)
NEWS_RUN_TYPES = ("news_link", "news_assess")
ZERO = Decimal(0)


class BudgetExceeded(Exception):
    """A call was not made. `kind` is month, news_share, daily_runs or price; the message is for
    the owner."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class Standing:
    month: str  # 2026-10
    spent_eur: Decimal
    news_spent_eur: Decimal
    budget_eur: Decimal
    news_share_eur: Decimal
    runs_this_month: int  # agent runs, not news steps
    runs_today: int
    daily_run_cap: int

    @property
    def remaining_eur(self) -> Decimal:
        return max(ZERO, self.budget_eur - self.spent_eur)


def agent_settings(db: Session) -> AgentSettings:
    cfg = AgentSettings.model_validate(load_section(db, "agent").model_dump())
    # settings saved before a run type existed have no model for it: fall back to the default
    cfg.models = {**AgentSettings().models, **cfg.models}
    return cfg


def timezone_of(db: Session) -> ZoneInfo:
    general = GeneralSettings.model_validate(load_section(db, "general").model_dump())
    return ZoneInfo(general.timezone)


def month_start(now: dt.datetime, tz: ZoneInfo) -> dt.datetime:
    local = now.astimezone(tz)
    return dt.datetime(local.year, local.month, 1, tzinfo=tz).astimezone(dt.UTC)


def day_start(now: dt.datetime, tz: ZoneInfo) -> dt.datetime:
    local = now.astimezone(tz)
    return dt.datetime(local.year, local.month, local.day, tzinfo=tz).astimezone(dt.UTC)


def standing(
    db: Session,
    cfg: AgentSettings,
    now: dt.datetime,
    tz: ZoneInfo,
    exclude_run: int | None = None,
) -> Standing:
    """What the month has cost and how many runs were made. `exclude_run` leaves one run out of
    the run counts (the one that is asking), though not out of the cost."""
    since, today = month_start(now, tz), day_start(now, tz)
    spent = news = ZERO
    runs = runs_today = 0
    for run in db.scalars(select(AgentRun).where(AgentRun.started_at >= since)):
        spent += run.cost_eur
        if run.run_type in NEWS_RUN_TYPES:
            news += run.cost_eur
        elif run.run_type in AGENT_RUN_TYPES and run.id != exclude_run:
            runs += 1
            runs_today += run.started_at >= today
    return Standing(
        month=now.astimezone(tz).strftime("%Y-%m"),
        spent_eur=spent,
        news_spent_eur=news,
        budget_eur=cfg.monthly_budget_eur,
        news_share_eur=cfg.news_share_eur,
        runs_this_month=runs,
        runs_today=runs_today,
        daily_run_cap=cfg.daily_run_cap,
    )


def usd_per_eur(db: Session, cfg: AgentSettings, day: dt.date) -> Decimal:
    try:
        return FxService(db).rate_per_eur("USD", day).rate_per_eur
    except FxUnavailable:
        return cfg.usd_per_eur_fallback


def price_for(cfg: AgentSettings, model: str) -> ModelPrice:
    price = cfg.prices.get(model)
    if price is None:
        raise BudgetExceeded(
            "price",
            f"There is no price for {model} in Settings, Agent, so its cost cannot be limited. "
            "Add one (US dollars per million tokens) or choose another model.",
        )
    return price


def check_call(
    db: Session,
    cfg: AgentSettings,
    now: dt.datetime,
    tz: ZoneInfo,
    *,
    run_type: str,
    worst_case_usd_amount: Decimal,
    new_run: bool = False,
    run_id: int | None = None,
) -> None:
    """Raise BudgetExceeded unless the call fits. `new_run` counts the call against the daily
    cap of agent runs (the first call of a run, which is not itself among the runs made)."""
    state = standing(db, cfg, now, tz, exclude_run=run_id if new_run else None)
    worst = to_eur(worst_case_usd_amount, usd_per_eur(db, cfg, now.date()))
    news = run_type in NEWS_RUN_TYPES
    if new_run and not news and state.runs_today >= state.daily_run_cap:
        raise BudgetExceeded(
            "daily_runs",
            f"The AI agent has made its {state.daily_run_cap} runs for today; it can run again "
            "tomorrow, or raise the cap in Settings, Agent.",
        )
    if state.spent_eur + worst > state.budget_eur:
        raise BudgetExceeded(
            "month",
            f"The AI budget for {state.month} is used up ({state.spent_eur:.2f} of "
            f"{state.budget_eur:.2f} EUR, and this call could cost up to {worst:.2f}). "
            "Raise it in Settings, Agent, or wait for next month.",
        )
    if news and state.news_spent_eur + worst > state.news_share_eur:
        raise BudgetExceeded(
            "news_share",
            f"News triage has used its share of the {state.month} AI budget "
            f"({state.news_spent_eur:.2f} of {state.news_share_eur:.2f} EUR). "
            "The rest is kept for the agent.",
        )


def charge(
    db: Session, run: AgentRun, cfg: AgentSettings, usage: Usage, model: str, day: dt.date
) -> Decimal:
    """Add a call's usage to its run and return what it cost in euro."""
    usd = cost_usd(usage, price_for(cfg, model), cfg.web_search_usd_per_1000)
    eur = to_eur(usd, usd_per_eur(db, cfg, day))
    run.input_tokens += usage.input_tokens
    run.output_tokens += usage.output_tokens
    run.cache_read_tokens += usage.cache_read_tokens
    run.cache_write_tokens += usage.cache_write_tokens
    run.web_searches += usage.web_searches
    run.cost_eur = run.cost_eur + eur
    db.flush()
    return eur


def stop_notice(
    db: Session, exc: BudgetExceeded, now: dt.datetime, tz: ZoneInfo, run_type: str
) -> bool:
    """Tell the owner once per month (or day) that the agent stopped. Returns whether a new
    notice was made."""
    if exc.kind in ("price", "run_tokens"):
        return False  # about one call or one run, not worth an inbox item
    period = (
        day_start(now, tz) if exc.kind == "daily_runs" else month_start(now, tz)
    )  # the notice is unique per period and kind
    subject = f"agent:{'news' if run_type in NEWS_RUN_TYPES else 'run'}:{exc.kind}"
    already = db.scalar(
        select(Notification.id).where(
            Notification.subject == subject, Notification.created_at >= period
        )
    )
    if already is not None:
        return False
    critical = db.scalar(
        select(Signal.id).where(
            Signal.severity == "critical",
            Signal.shadow.is_(False),
            Signal.ts >= now - dt.timedelta(days=7),
        )
    )
    title = {
        "month": "The AI agent is paused: this month's budget is used up",
        "news_share": "News triage is paused: its share of the AI budget is used up",
        "daily_runs": "The AI agent is paused for today: the daily run cap is reached",
    }[exc.kind]
    notify(
        db,
        source="system",
        severity="critical" if critical is not None else "medium",
        subject=subject,
        title=title,
        body=f"{exc} Rules, alerts and notifications keep working.",
        push_body=title,
        push_body_anonymous="Folio has a new item.",
        link="/system",
        now=now,
    )
    return True
