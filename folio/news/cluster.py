"""Grouping items about the same story (FR-NW-04).

Two items belong together when they were published within 48 hours of each other and their
headlines say much the same: at least half of their meaningful words are shared, or at least
30 % when both are linked to the same holding (a headline about ASML from two sources needs
less in common). An item whose headline is word for word the same always joins.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

WINDOW = timedelta(hours=48)
SIMILAR = Decimal("0.5")
SIMILAR_WITH_SHARED_ENTITY = Decimal("0.3")


@dataclass(frozen=True)
class Member:
    tokens: frozenset[str]  # the meaningful words of the headline
    entities: frozenset[str]  # what the item is linked to (instrument ids, as text)
    published: datetime
    content_hash: str


@dataclass
class ClusterState:
    id: int | None
    members: list[Member] = field(default_factory=list)

    @property
    def first_seen(self) -> datetime:
        return min(m.published for m in self.members)

    @property
    def last_seen(self) -> datetime:
        return max(m.published for m in self.members)


def similarity(a: frozenset[str], b: frozenset[str]) -> Decimal:
    """Shared words as a share of all the words of both headlines (0 to 1)."""
    if not a or not b:
        return Decimal(0)
    return Decimal(len(a & b)) / Decimal(len(a | b))


def score(a: Member, b: Member) -> Decimal | None:
    """How alike two items are, or None when they are not the same story."""
    if abs(a.published - b.published) > WINDOW:
        return None
    if a.content_hash == b.content_hash:
        return Decimal(1)
    s = similarity(a.tokens, b.tokens)
    needed = SIMILAR_WITH_SHARED_ENTITY if a.entities & b.entities else SIMILAR
    return s if s >= needed else None


def best_cluster(member: Member, clusters: Sequence[ClusterState]) -> ClusterState | None:
    """The cluster whose closest member is most like this item, if any is like it at all."""
    best: tuple[Decimal, ClusterState] | None = None
    for cluster in clusters:
        scores = [s for m in cluster.members if (s := score(member, m)) is not None]
        if scores and (best is None or max(scores) > best[0]):
            best = (max(scores), cluster)
    return None if best is None else best[1]
