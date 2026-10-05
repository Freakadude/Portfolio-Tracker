"""Assessing stories with the LLM (FR-NW-05, FR-NW-06).

Stories linked to a holding are assessed in batches by the cheap model; one call both scores the
stories and adds thematic and macro links the text matching cannot find. A story that scores high,
or touches a big position, is assessed again by the stronger model. A story that scores high
enough on a holding becomes a high notification, and the agent's event run (step 8) picks up
stories at or above the event threshold.

Every call goes through the budget (ADR 0028); when it refuses, the stories wait for next time.
Text from outside only ever travels inside `<untrusted>` blocks.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.agent import budget
from folio.agent.llm import LlmClient, LlmError, system_blocks
from folio.agent.prompt_files import labels, load_prompt
from folio.agent.runs import finish_run, metered_create, start_run
from folio.db.models_insight import (
    NewsAssessment,
    NewsCluster,
    NewsItem,
    NewsLink,
    NewsSource,
)
from folio.db.models_ledger import Instrument
from folio.db.models_strategy import Notification
from folio.news import triage
from folio.news.linking import relevance
from folio.news.pipeline import World, build_world
from folio.notify.service import notify
from folio.settings_schema import NewsSettings
from folio.settings_store import load_section

HUNDRED = Decimal(100)
ZERO = Decimal(0)
ITEMS_PER_STORY = 4
SUMMARY_CHARS = 300
ESCALATED_SUMMARY_CHARS = 500
LLM_PREFIX = "llm:"
_SLUG = re.compile(r"[^a-z0-9 ]+")


@dataclass
class Result:
    assessed: int = 0
    escalated: int = 0
    notified: int = 0
    links_added: int = 0
    cost_eur: Decimal = ZERO
    problems: list[str] = field(default_factory=list)
    stopped: str | None = None  # why the rest was left for next time


def news_settings(db: Session) -> NewsSettings:
    return NewsSettings.model_validate(load_section(db, "news").model_dump())


def _options(db: Session, world: World) -> tuple[list[triage.Option], list[triage.Option]]:
    names = {
        i.id: i.name
        for i in db.scalars(select(Instrument).where(Instrument.id.in_(list(world.exposure))))
    }
    holdings = [
        triage.Option(
            f"instrument:{i}",
            names.get(i, f"Instrument {i}"),
            (share * HUNDRED).quantize(Decimal("0.1")),
        )
        for i, share in sorted(world.exposure.items(), key=lambda kv: -kv[1])
        if share > 0
    ]
    sleeves = [triage.Option(f"sleeve:{s}", s) for s in sorted(world.sleeve_exposure)]
    return holdings, sleeves


def _eligible(
    db: Session, now: dt.datetime, tz: ZoneInfo, cfg: NewsSettings, sources: dict[int, NewsSource]
) -> list[NewsCluster]:
    """Stories worth assessing: recent, not assessed, and linked (or a limited number of
    unlinked ones from sources the owner trusts)."""
    floor = now - dt.timedelta(days=cfg.max_age_days)
    rows = list(
        db.scalars(
            select(NewsCluster)
            .where(
                NewsCluster.assessed.is_(False),
                NewsCluster.last_seen >= floor,
                NewsCluster.linked.is_(True),
            )
            .order_by(NewsCluster.relevance.desc(), NewsCluster.last_seen.desc())
        )
    )
    linked = [c for c in rows if c.relevance >= cfg.min_relevance]
    today = budget.day_start(now, tz)
    done_unlinked = sum(
        1
        for c in db.scalars(
            select(NewsCluster)
            .join(NewsAssessment, NewsAssessment.cluster_id == NewsCluster.id)
            .where(NewsAssessment.created_at >= today, NewsCluster.relevance < cfg.min_relevance)
        ).unique()
    )
    room = max(0, cfg.unlinked_per_day - done_unlinked)
    unlinked: list[NewsCluster] = []
    for c in rows:
        if c.relevance >= cfg.min_relevance or len(unlinked) >= room:
            continue
        trusted = any(
            sources[i.source_id].trust_weight >= Decimal("0.5")
            for i in db.scalars(select(NewsItem).where(NewsItem.cluster_id == c.id))
            if i.source_id in sources
        )
        if trusted:
            unlinked.append(c)
    return (linked + unlinked)[: cfg.max_per_run]


def _pack(
    db: Session,
    cluster: NewsCluster,
    sources: dict[int, NewsSource],
    names: dict[int, str],
    chars: int,
) -> triage.ClusterPack:
    items = list(
        db.scalars(
            select(NewsItem)
            .where(NewsItem.cluster_id == cluster.id)
            .order_by(NewsItem.published_at)
            .limit(ITEMS_PER_STORY)
        )
    )
    links = db.scalars(
        select(NewsLink).where(
            NewsLink.cluster_id == cluster.id, ~NewsLink.matched_by.startswith(LLM_PREFIX)
        )
    )
    return triage.ClusterPack(
        cluster.id,
        [
            triage.ItemPack(
                sources[i.source_id].name if i.source_id in sources else "?",
                sources[i.source_id].trust_weight if i.source_id in sources else ZERO,
                i.published_at,
                i.title,
                i.summary[:chars],
            )
            for i in items
        ],
        [
            triage.LinkPack(
                names.get(link.instrument_id or 0, link.sleeve or "?"),
                link.link_type,
                link.weight_pct,
                link.matched_by,
            )
            for link in links
        ],
    )


def _touched_weight_pct(db: Session, world: World, cluster_id: int) -> Decimal:
    """The largest share of the portfolio among the positions a story is linked to."""
    shares = [
        world.exposure.get(link.instrument_id, ZERO)
        for link in db.scalars(select(NewsLink).where(NewsLink.cluster_id == cluster_id))
        if link.instrument_id is not None and link.link_type in ("direct", "look_through")
    ]
    return max(shares, default=ZERO) * HUNDRED


def _store(
    db: Session,
    world: World,
    sources: dict[int, NewsSource],
    now: dt.datetime,
    item: triage.Assessed,
    model: str,
    cost: Decimal,
) -> int:
    """Save an assessment and the links the model added; returns how many links."""
    cluster = db.get(NewsCluster, item.cluster_id)
    if cluster is None:
        return 0
    db.add(
        NewsAssessment(
            cluster_id=cluster.id,
            impact_score=item.impact,
            direction=item.direction,
            horizon=item.horizon,
            affected=item.affected,
            rationale=item.rationale,
            confidence=item.confidence,
            model=model,
            cost_eur=cost,
        )
    )
    cluster.assessed, cluster.max_impact = True, item.impact
    trust = max(
        (
            sources[i.source_id].trust_weight
            for i in db.scalars(select(NewsItem).where(NewsItem.cluster_id == cluster.id))
            if i.source_id in sources
        ),
        default=Decimal("0.5"),
    )
    existing = {
        (link.instrument_id, link.sleeve, link.link_type)
        for link in db.scalars(select(NewsLink).where(NewsLink.cluster_id == cluster.id))
    }
    added = 0
    for new in item.links:
        kind_, _, ident = new.target.partition(":")
        instrument_id = int(ident) if kind_ == "instrument" and ident.isdigit() else None
        sleeve = ident if kind_ == "sleeve" else None
        key = (instrument_id, sleeve, new.kind)
        if key in existing or (instrument_id is None and sleeve is None):
            continue
        existing.add(key)
        share = (
            world.exposure.get(instrument_id, ZERO)
            if instrument_id is not None
            else world.sleeve_exposure.get(sleeve or "", ZERO)
        )
        link = NewsLink(
            cluster_id=cluster.id,
            instrument_id=instrument_id,
            sleeve=sleeve,
            link_type=new.kind,
            relevance=relevance(new.kind, share, trust, now - cluster.last_seen),
            matched_by=f"{LLM_PREFIX}{new.kind}:{_SLUG.sub('', new.reason.lower())[:70]}".rstrip(),
        )
        db.add(link)
        cluster.relevance = max(cluster.relevance, link.relevance)
        added += 1
    return added


def _notify(
    db: Session, world: World, now: dt.datetime, cluster: NewsCluster, impact: int, why: str
) -> bool:
    subject = f"news:{cluster.id}"
    if db.scalar(select(Notification.id).where(Notification.subject == subject)) is not None:
        return False
    title = cluster.title
    notify(
        db,
        source="news",
        severity="high",
        subject=subject,
        title=f"News on a holding: {title}",
        body=f"{why}\n\nImpact {impact} of 100.",
        push_title="Folio: important news",
        push_body=f"News on a holding: {title}"[:400],
        push_body_anonymous="A story about one of your holdings may matter.",
        link=f"/news?cluster={cluster.id}",
        now=now,
    )
    return True


def assess_news(db: Session, llm: LlmClient | None, now: dt.datetime) -> Result:
    result = Result()
    news_cfg, agent_cfg = news_settings(db), budget.agent_settings(db)
    if llm is None or not agent_cfg.enabled or not news_cfg.triage:
        result.stopped = "off"
        return result
    tz = budget.timezone_of(db)
    sources = {s.id: s for s in db.scalars(select(NewsSource))}
    clusters = _eligible(db, now, tz, news_cfg, sources)
    if not clusters:
        return result
    world = build_world(db, now)
    holdings, sleeves = _options(db, world)
    names = {int(o.ref.split(":")[1]): o.label for o in holdings}
    instrument_refs = [o.ref for o in holdings]
    target_refs = instrument_refs + [o.ref for o in sleeves]
    prompts = [load_prompt("system"), load_prompt("news_assess")]
    system = system_blocks(prompts[0].text, prompts[1].text)
    db.commit()  # no write lock is held across the calls below

    def call(
        model: str, packs: Sequence[triage.ClusterPack]
    ) -> tuple[list[triage.Assessed], Decimal] | None:
        ids = [p.id for p in packs]
        run = start_run(db, "news", "news_assess", model, labels(prompts), now)
        user = triage.build_prompt(packs, holdings, sleeves)
        run.context = {"clusters": ids, "message": user}
        try:
            reply = metered_create(
                db, llm, agent_cfg, tz, now, run, model=model, system=system,
                messages=[{"role": "user", "content": user}],
                max_tokens=600 + 350 * len(packs),
                output_schema=triage.build_schema(ids, instrument_refs, target_refs),
            )  # fmt: skip
        except budget.BudgetExceeded as exc:
            finish_run(db, run, now, "budget", str(exc))
            budget.stop_notice(db, exc, now, tz, "news_assess")
            db.commit()
            result.stopped = exc.kind
            return None
        except LlmError as exc:
            finish_run(db, run, now, "failed", str(exc))
            db.commit()
            result.problems.append(str(exc))
            result.stopped = exc.kind
            return None
        found, problems = triage.parse_reply(reply.text, ids, instrument_refs, target_refs)
        run.output = {"text": reply.text, "problems": problems}
        run.digest = f"{len(found)} of {len(ids)} stories assessed"
        result.problems += problems
        finish_run(
            db, run, now, "ok" if found else "failed", None if found else "; ".join(problems)
        )
        result.cost_eur += run.cost_eur
        db.commit()
        return found, (run.cost_eur / len(found) if found else ZERO)

    for start in range(0, len(clusters), news_cfg.batch_size):
        batch = clusters[start : start + news_cfg.batch_size]
        packs = [_pack(db, c, sources, names, SUMMARY_CHARS) for c in batch]
        answered = call(agent_cfg.models["news_triage"], packs)
        if answered is None:
            break
        found, share = answered
        for item in found:
            result.links_added += _store(
                db, world, sources, now, item, agent_cfg.models["news_triage"], share
            )
            result.assessed += 1
        db.commit()
        for item in found:
            cluster = db.get(NewsCluster, item.cluster_id)
            if cluster is None or not triage.needs_escalation(
                item.impact,
                _touched_weight_pct(db, world, cluster.id),
                news_cfg.escalate_impact,
                news_cfg.escalate_weight_pct,
            ):
                continue
            model = agent_cfg.models["news_escalation"]
            again = call(model, [_pack(db, cluster, sources, names, ESCALATED_SUMMARY_CHARS)])
            if again is None:
                break
            for second in again[0]:
                result.links_added += _store(db, world, sources, now, second, model, again[1])
                result.escalated += 1
            db.commit()
        if result.stopped:
            break

    for cluster in db.scalars(
        select(NewsCluster).where(
            NewsCluster.assessed.is_(True), NewsCluster.max_impact >= news_cfg.push_impact
        )
    ):
        touched = _touched_weight_pct(db, world, cluster.id) > 0 or any(
            world.sleeve_exposure.get(link.sleeve or "", ZERO) > 0
            for link in db.scalars(select(NewsLink).where(NewsLink.cluster_id == cluster.id))
            if link.sleeve
        )
        if touched:
            latest = db.scalars(
                select(NewsAssessment)
                .where(NewsAssessment.cluster_id == cluster.id)
                .order_by(NewsAssessment.id.desc())
            ).first()
            result.notified += _notify(
                db,
                world,
                now,
                cluster,
                int(cluster.max_impact or 0),
                latest.rationale if latest else "",
            )
    db.commit()
    return result
