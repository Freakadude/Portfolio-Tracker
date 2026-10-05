"""One agent run (FR-AG-01, FR-AG-02, FR-AG-03; spec section 11).

1. Gather: the context pack (strategy, signals, linked news, recent recommendations).
2. Investigate: a tool loop with the read-only tools and, when the owner has listed trusted
   domains, the server-side web search, ending in free-text findings.
3. Compose: a second call turns the findings into recommendations with structured outputs (a
   separate call, because structured outputs cannot be combined with citations).
4. Validate: the code gate (folio/agent/validate.py) decides what is shown.
5. Deliver: accepted items go to the inbox through the notification routing; refused ones are
   kept with their reasons and never shown as advice.

Every call is metered against the budget. The whole trace (context, tool calls, findings, the raw
answer, the verdicts, tokens and cost) is kept in `agent_run`.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.agent import budget
from folio.agent.context import build_pack
from folio.agent.facts import FactsBuilder
from folio.agent.llm import (
    LlmClient,
    LlmError,
    Reply,
    system_blocks,
    web_search_tool,
    with_cache,
)
from folio.agent.prompt_files import labels, load_prompt
from folio.agent.runs import finish_run, metered_create, start_run
from folio.agent.schema import RECOMMENDATION_SCHEMA
from folio.agent.tools import TOOL_DEFS, ToolBox
from folio.agent.validate import Checked, Past, Rec, Verdict, check_output
from folio.db.models_insight import AgentRun, Recommendation
from folio.db.models_ledger import Instrument, PriceBar
from folio.events import RECOMMENDATION, publish_event
from folio.instruments import primary_listing
from folio.news.normalize import canonical_url
from folio.notify.service import notify

MAX_STEPS = 14
INVESTIGATE_TOKENS = 4000
COMPOSE_TOKENS = 4000
RESULT_CHARS = 12000
LABEL = "AI-generated, not financial advice."
ZERO = Decimal(0)


@dataclass
class Outcome:
    run_id: int
    status: str  # ok | failed | budget
    accepted: list[int] = field(default_factory=list)  # ids of the recommendations made
    refused: int = 0
    digest: str = ""
    cost_eur: Decimal = ZERO
    stopped: str | None = None
    error: str | None = None


def _past(db: Session, now: dt.datetime) -> list[Past]:
    since = now - dt.timedelta(days=15)
    return [
        Past(frozenset(r.subjects or []), r.action_type, r.created_at, r.status)
        for r in db.scalars(select(Recommendation).where(Recommendation.created_at >= since))
    ]


def _subject_prices(db: Session, subjects: tuple[str, ...]) -> dict[str, str]:
    """The last close of each subject that is an instrument (name, ISIN or id), so the track
    record can compare later (FR-AG-06)."""
    prices: dict[str, str] = {}
    for subject in subjects:
        instrument = db.scalar(
            select(Instrument).where(
                (Instrument.name == subject)
                | (Instrument.isin == subject)
                | (Instrument.id == int(subject) if subject.isdigit() else False)  # noqa: SIM300
            )
        )
        if instrument is None:
            continue
        listing = primary_listing(db, instrument.id)
        if listing is None:
            continue
        bar = db.scalars(
            select(PriceBar).where(PriceBar.listing_id == listing.id).order_by(PriceBar.date.desc())
        ).first()
        if bar is not None:
            prices[subject] = str(bar.close)
    return prices


def _calc_id(value: str | None) -> int | None:
    if value and value.startswith("calc-") and value[5:].isdigit():
        return int(value[5:])
    return None


def _store_accepted(db: Session, run: AgentRun, rec: Rec, now: dt.datetime) -> Recommendation:
    row = Recommendation(
        run_id=run.id,
        action_type=rec.action_type,
        severity=rec.severity,
        subjects=list(rec.subjects),
        title=rec.title[:200],
        summary=rec.summary,
        rationale=rec.rationale,
        calculation_id=_calc_id(rec.calculation_id),
        evidence=[{"kind": e.kind, "ref": e.ref, "note": e.note} for e in rec.evidence],
        sources=list(rec.sources),
        confidence=rec.confidence,
        departs_from_principles=rec.departs_from_principles,
        what_would_change_this=rec.what_would_change_this,
        expires_at=now + dt.timedelta(days=rec.expires_in_days),
        status="new",
        price_at_creation=_subject_prices(db, rec.subjects),
    )
    db.add(row)
    db.flush()
    publish_event(db, RECOMMENDATION, {"id": row.id, "status": "new", "what": "created"})
    return row


def _store_refused(
    db: Session, run: AgentRun, raw: Any, verdict: Verdict, now: dt.datetime
) -> None:
    item = raw if isinstance(raw, dict) else {}
    db.add(
        Recommendation(
            run_id=run.id,
            action_type=str(item.get("action_type", "info"))[:20],
            severity=str(item.get("severity", "info"))[:10],
            subjects=[str(s) for s in item.get("subjects", []) if isinstance(s, str)],
            title=str(item.get("title", "(unreadable)"))[:200],
            summary=str(item.get("summary", "")),
            rationale=str(item.get("rationale", "")),
            confidence=str(item.get("confidence", "low"))[:6],
            what_would_change_this=str(item.get("what_would_change_this", "")),
            expires_at=now,
            status="refused",
            refused_reason="; ".join(verdict.reasons),
        )
    )


def _deliver(db: Session, row: Recommendation, now: dt.datetime) -> None:
    badge = (
        "\nThis advice departs from your principles: " + row.departs_from_principles
        if row.departs_from_principles
        else ""
    )
    notify(
        db,
        source="agent",
        severity=row.severity,
        subject=(row.subjects[0] if row.subjects else row.title)[:120],
        title=row.title,
        body=f"{row.summary}\n\n{row.rationale}{badge}\n\n{LABEL}",
        push_title="Folio: recommendation",
        push_body=f"{row.title}"[:400],
        push_body_anonymous="Folio has a new recommendation.",
        link=f"/insights?recommendation={row.id}",
        now=now,
    )


def _tool_result(result: dict[str, Any]) -> str:
    text = json.dumps(result, default=str)
    if len(text) > RESULT_CHARS:
        return json.dumps({"truncated": True, "text": text[:RESULT_CHARS]})
    return text


def run_agent(
    db: Session,
    llm: LlmClient,
    now: dt.datetime,
    *,
    run_type: str,
    trigger: str,
    focus: str | None = None,
) -> Outcome:
    cfg = budget.agent_settings(db)
    tz = budget.timezone_of(db)
    model = cfg.models[run_type]
    prompts = [load_prompt("system"), load_prompt("investigate"), load_prompt("compose")]
    run = start_run(db, trigger, run_type, model, labels(prompts), now)
    outcome = Outcome(run.id, "ok")
    facts = FactsBuilder()
    tools = ToolBox(db, now, cfg.privacy_mode, facts)
    tool_calls: list[dict[str, Any]] = []
    try:
        pack_text, pack = build_pack(tools, run_type, trigger, focus, now)
        run.context = pack
        db.commit()
        findings = _investigate(
            db, llm, cfg, tz, now, run, model, prompts, tools, facts, pack_text, tool_calls
        )
        run.findings = findings
        run.tool_calls = tool_calls
        raw_text = _compose(db, llm, cfg, tz, now, run, model, prompts, findings, tool_calls)
        checked, data = _check(db, raw_text, facts, now)
        _persist(db, run, now, checked, data, raw_text, outcome, deliver=True)
        run.digest = checked.digest
        outcome.digest = checked.digest
        if run_type in ("daily_review", "weekly_review"):
            _digest_item(db, run_type, checked, outcome, now)
        finish_run(
            db,
            run,
            now,
            "ok" if not checked.problems else "failed",
            "; ".join(checked.problems) or None,
        )
        outcome.status = run.status
    except budget.BudgetExceeded as exc:
        run.tool_calls = tool_calls
        finish_run(db, run, now, "budget", str(exc))
        budget.stop_notice(db, exc, now, tz, run_type)
        outcome.status, outcome.stopped, outcome.error = "budget", exc.kind, str(exc)
    except LlmError as exc:
        run.tool_calls = tool_calls
        finish_run(db, run, now, "failed", str(exc))
        outcome.status, outcome.stopped, outcome.error = "failed", exc.kind, str(exc)
    except (ValueError, KeyError) as exc:  # an answer that could not be read
        run.tool_calls = tool_calls
        finish_run(db, run, now, "failed", f"The answer could not be read: {exc}")
        outcome.status, outcome.error = "failed", str(exc)
    outcome.cost_eur = run.cost_eur
    db.commit()
    return outcome


def _investigate(
    db: Session,
    llm: LlmClient,
    cfg: Any,
    tz: Any,
    now: dt.datetime,
    run: AgentRun,
    model: str,
    prompts: list[Any],
    tools: ToolBox,
    facts: FactsBuilder,
    pack_text: str,
    tool_calls: list[dict[str, Any]],
) -> str:
    system = system_blocks(prompts[0].text, prompts[1].text)
    defs = list(TOOL_DEFS)
    if cfg.web_search_domains and cfg.web_search_max_uses > 0:
        defs.append(web_search_tool(cfg.web_search_domains, cfg.web_search_max_uses))
    messages: list[dict[str, Any]] = [{"role": "user", "content": pack_text}]
    last_text = ""
    for step in range(MAX_STEPS):
        reply: Reply = metered_create(
            db, llm, cfg, tz, now, run, model=model, system=system, messages=messages,
            max_tokens=INVESTIGATE_TOKENS, tools=with_cache(defs),
            max_searches=cfg.web_search_max_uses if cfg.web_search_domains else 0,
            new_run=step == 0,
        )  # fmt: skip
        for search in reply.searches:
            tool_calls.append(
                {
                    "name": "web_search",
                    "input": {"query": search["query"]},
                    "result": search["urls"],
                }
            )
            facts.urls |= {canonical_url(u) for u in search["urls"] if isinstance(u, str)}
        last_text = reply.text or last_text
        messages.append({"role": "assistant", "content": reply.content})
        if reply.stop_reason == "tool_use" and reply.tool_uses:
            results: list[dict[str, Any]] = []
            for use in reply.tool_uses:
                result, failed = tools.run(use.name, use.input)
                tool_calls.append(
                    {
                        "name": use.name,
                        "input": use.input,
                        "error": failed,
                        "result": _tool_result(result)[:1500],
                    }
                )
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": use.id,
                        "content": _tool_result(result),
                        "is_error": failed,
                    }
                )
            messages.append({"role": "user", "content": results})
            continue
        if reply.stop_reason == "pause_turn":
            continue  # a server-side tool is still working: send its blocks back as they are
        return reply.text or last_text
    return last_text + "\n(The investigation stopped at its step limit.)"


def _compose(
    db: Session,
    llm: LlmClient,
    cfg: Any,
    tz: Any,
    now: dt.datetime,
    run: AgentRun,
    model: str,
    prompts: list[Any],
    findings: str,
    tool_calls: list[dict[str, Any]],
) -> str:
    system = system_blocks(prompts[0].text, prompts[2].text)
    called = sorted({str(c["name"]) for c in tool_calls})
    user = (
        f"Findings of the investigation:\n{findings}\n\n"
        f"Tools used in the investigation: {', '.join(called) or 'none'}."
    )
    reply = metered_create(
        db, llm, cfg, tz, now, run, model=model, system=system,
        messages=[{"role": "user", "content": user}], max_tokens=COMPOSE_TOKENS,
        output_schema=RECOMMENDATION_SCHEMA,
    )  # fmt: skip
    return reply.text


def _check(db: Session, text: str, facts: FactsBuilder, now: dt.datetime) -> tuple[Checked, Any]:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"the composed answer is not JSON ({exc})") from exc
    return check_output(data, facts.freeze(), _past(db, now), now), data


def _persist(
    db: Session,
    run: AgentRun,
    now: dt.datetime,
    checked: Checked,
    data: Any,
    raw_text: str,
    outcome: Outcome,
    *,
    deliver: bool,
) -> None:
    raw_items = data.get("recommendations", []) if isinstance(data, dict) else []
    for verdict in checked.verdicts:
        if verdict.accepted and verdict.rec is not None:
            row = _store_accepted(db, run, verdict.rec, now)
            outcome.accepted.append(row.id)
            if deliver:
                _deliver(db, row, now)
        else:
            _store_refused(
                db,
                run,
                raw_items[verdict.index] if verdict.index < len(raw_items) else None,
                verdict,
                now,
            )
            outcome.refused += 1
    run.output = {
        "text": raw_text,
        "problems": checked.problems,
        "verdicts": [
            {"index": v.index, "accepted": v.accepted, "reasons": list(v.reasons)}
            for v in checked.verdicts
        ],
    }


def _digest_item(
    db: Session, run_type: str, checked: Checked, outcome: Outcome, now: dt.datetime
) -> None:
    """The run's digest as an info item, so a quiet day is visible too ("nothing needs
    attention")."""
    title = "Daily review" if run_type == "daily_review" else "Weekly review"
    body = checked.digest or "The review made no comment."
    extra = (
        f"{len(outcome.accepted)} recommendation(s) made."
        if outcome.accepted
        else "No recommendations."
    )
    notify(
        db,
        source="agent",
        severity="info",
        subject=f"{run_type} digest",
        title=f"{title}: {body[:120]}",
        body=f"{body}\n\n{extra}\n\n{LABEL}",
        push_title=f"Folio {title.lower()}",
        push_body=body[:300],
        push_body_anonymous="Folio has a new review.",
        link="/insights",
        now=now,
    )
