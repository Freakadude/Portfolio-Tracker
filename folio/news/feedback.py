"""The owner's feedback on a story (FR-NW-08): "useful" and "not relevant".

Five more "not relevant" than "useful" marks on a source's stories lower its trust by 0.1 (and
back up for useful ones), and the alias that found a wrongly linked story loses weight until it
stops matching (ADR 0027). Marking the same story the same way twice changes nothing; marking it
the other way undoes the first mark's effect on the source.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from folio.audit import write_audit
from folio.db.models_insight import InstrumentAlias, NewsFeedback, NewsItem, NewsLink, NewsSource
from folio.news import triage

VERDICTS = ("useful", "not_relevant")
LLM_PREFIX = "llm:"


class FeedbackError(ValueError):
    """The feedback cannot be recorded; the message is for the owner."""


@dataclass(frozen=True)
class Change:
    kind: str  # source_trust | alias_weight
    name: str
    old: Decimal
    new: Decimal


def _balance(db: Session, source_id: int) -> int:
    marks = db.scalars(select(NewsFeedback.verdict).where(NewsFeedback.source_id == source_id))
    return sum(1 if v == "not_relevant" else -1 for v in marks)


def give_feedback(
    db: Session,
    cluster_id: int,
    verdict: str,
    link_id: int | None = None,
    actor: str = "user",
) -> list[Change]:
    from folio.db.models_insight import NewsCluster  # noqa: PLC0415 - avoids a wider import list

    if verdict not in VERDICTS:
        raise FeedbackError("The verdict must be useful or not_relevant.")
    cluster = db.get(NewsCluster, cluster_id)
    if cluster is None:
        raise FeedbackError("That story does not exist.")
    source_ids = sorted(
        set(db.scalars(select(NewsItem.source_id).where(NewsItem.cluster_id == cluster_id)))
    )
    if link_id is not None:
        link = db.get(NewsLink, link_id)
        if link is None or link.cluster_id != cluster_id:
            raise FeedbackError("That link does not belong to this story.")
    already = db.scalar(
        select(NewsFeedback.id).where(
            NewsFeedback.cluster_id == cluster_id, NewsFeedback.verdict == verdict
        )
    )
    changes: list[Change] = []
    for source_id in source_ids:
        source = db.get(NewsSource, source_id)
        if source is None:
            continue
        before = _balance(db, source_id)
        db.execute(
            delete(NewsFeedback).where(
                NewsFeedback.cluster_id == cluster_id, NewsFeedback.source_id == source_id
            )
        )
        db.add(NewsFeedback(cluster_id=cluster_id, source_id=source_id, verdict=verdict))
        db.flush()
        new_trust = triage.trust_after(source.trust_weight, before, _balance(db, source_id))
        if new_trust != source.trust_weight:
            changes.append(Change("source_trust", source.name, source.trust_weight, new_trust))
            write_audit(
                db, actor, "news_source", "feedback", entity_id=source.id,
                diff={"trust_weight": {"old": str(source.trust_weight), "new": str(new_trust)}},
            )  # fmt: skip
            source.trust_weight = new_trust
    if already is not None:
        db.flush()
        return changes  # the same mark twice does not count twice
    links = db.scalars(
        select(NewsLink).where(
            NewsLink.cluster_id == cluster_id,
            ~NewsLink.matched_by.startswith(LLM_PREFIX),
            *([NewsLink.id == link_id] if link_id is not None else []),
        )
    )
    for link in links:
        if not link.matched_by.startswith("alias:") or link.instrument_id is None:
            continue
        alias = db.scalar(
            select(InstrumentAlias).where(
                InstrumentAlias.instrument_id == link.instrument_id,
                InstrumentAlias.alias == link.matched_by.removeprefix("alias:"),
            )
        )
        if alias is None:
            continue
        new_weight = triage.alias_after(alias.weight, verdict)
        if new_weight != alias.weight:
            changes.append(Change("alias_weight", alias.alias, alias.weight, new_weight))
            write_audit(
                db, actor, "instrument_alias", "feedback", entity_id=alias.id,
                diff={"weight": {"old": str(alias.weight), "new": str(new_weight)}},
            )  # fmt: skip
            alias.weight = new_weight
    db.flush()
    return changes
