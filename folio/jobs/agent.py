"""When the agent runs (FR-AG-01).

A check every five minutes decides what is due, so a changed review time or a new signal is seen
within minutes, and nothing is written when nothing is due:

- the daily review on weekdays from the configured time (default 19:30), once a day;
- an event run for a high or critical signal (once per subject per day) and for a news story
  scoring at or above the event threshold (once per story);
- a contribution-plan run when a `contribution_due` signal appears (off while no plan is set);
- on demand, from a job request.

With the agent off or without an API key nothing is due and nothing is called.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.agent import budget
from folio.agent.run import run_agent
from folio.agent.tools import untrusted
from folio.db.models_insight import AgentRun, NewsCluster
from folio.db.models_strategy import Signal
from folio.jobs.context import JobContext
from folio.jobs.runner import JobLog, JobResult, run_job
from folio.news.assess import news_settings

MAX_PER_TICK = 2
EVENT_SEVERITIES = ("high", "critical")


@dataclass(frozen=True)
class Due:
    run_type: str
    trigger: str
    focus: str | None = None


def _ran(db: Session, trigger: str, since: dt.datetime | None) -> bool:
    query = select(AgentRun.id).where(AgentRun.trigger == trigger)
    if since is not None:
        query = query.where(AgentRun.started_at >= since)
    return db.scalar(query.limit(1)) is not None


def due_runs(db: Session, now: dt.datetime) -> list[Due]:
    cfg = budget.agent_settings(db)
    if not cfg.enabled:
        return []
    tz = budget.timezone_of(db)
    today = budget.day_start(now, tz)
    due: list[Due] = []
    local = now.astimezone(tz)
    hour, minute = (int(p) for p in cfg.daily_review_time.split(":"))
    after_review_time = (local.hour, local.minute) >= (hour, minute)
    if local.weekday() < 5 and after_review_time and not _ran(db, "daily", today):
        due.append(Due("daily_review", "daily"))
    recent = now - dt.timedelta(hours=24)
    handled: set[str] = set()
    for sig in db.scalars(
        select(Signal)
        .where(Signal.shadow.is_(False), Signal.ts >= recent, Signal.severity.in_(EVENT_SEVERITIES))
        .order_by(Signal.ts)
    ):
        if sig.rule_type == "contribution_due":
            trigger = f"contribution:{sig.id}"
            if not _ran(db, trigger, None) and trigger not in handled:
                handled.add(trigger)
                due.append(Due("contribution_plan", trigger, sig.message[:300]))
            continue
        trigger = f"event:{sig.subject}"[:60]
        if trigger in handled or _ran(db, trigger, today):
            continue
        handled.add(trigger)
        due.append(
            Due(
                "event_run", trigger, f"{sig.severity} signal on {sig.subject}: {sig.message}"[:300]
            )
        )
    threshold = news_settings(db).event_impact
    for cluster in db.scalars(
        select(NewsCluster)
        .where(
            NewsCluster.assessed.is_(True),
            NewsCluster.max_impact >= threshold,
            NewsCluster.last_seen >= recent,
        )
        .order_by(NewsCluster.max_impact.desc())
    ):
        trigger = f"event:news:{cluster.id}"
        if trigger in handled or _ran(db, trigger, None):
            continue
        handled.add(trigger)
        due.append(
            Due(
                "event_run",
                trigger,
                f"News story {cluster.id}, impact {cluster.max_impact}: {untrusted(cluster.title)}",
            )
        )
    return due


def agent_run_job(
    ctx: JobContext, run_type: str, trigger: str, focus: str | None = None
) -> JobResult:
    def body(db: Session, log: JobLog) -> None:
        llm = ctx.llm_for(db)
        if llm is None:
            log.info("The agent is switched off or has no API key.")
            return
        outcome = run_agent(db, llm, ctx.now(), run_type=run_type, trigger=trigger, focus=focus)
        log.info(
            f"{run_type} ({trigger}): {outcome.status}, {len(outcome.accepted)} recommendation(s), "
            f"{outcome.refused} refused, {outcome.cost_eur:.4f} EUR"
        )
        if outcome.status == "failed":
            log.error(outcome.error or "The run failed.")
        elif outcome.status == "budget":
            log.info(f"Paused: {outcome.error}")

    return run_job(ctx, "agent", body, {"run_type": run_type, "trigger": trigger})


def agent_tick(ctx: JobContext) -> int:
    """Run whatever is due; returns how many runs were made."""
    with ctx.session_factory() as db:
        if ctx.llm_for(db) is None:
            return 0
        due = due_runs(db, ctx.now())[:MAX_PER_TICK]
    for item in due:
        agent_run_job(ctx, item.run_type, item.trigger, item.focus)
    return len(due)
