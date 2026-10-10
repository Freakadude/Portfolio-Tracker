"""From stored items to clusters and links (FR-NW-04, FR-NW-05, FR-NW-10).

Runs after each fetch on the items that have no cluster yet: each joins the cluster of the story
it repeats (or starts a new one), then every touched cluster is linked to what the owner holds:
directly (an ISIN, ticker or name in the text), through an ETF that holds the company, and, for
a central bank's rate and currency news, to the sleeves whose rules watch those series. Which
words the LLM adds (themes, wider macro links) is a later step and is kept apart: its links carry
`llm:` in `matched_by` and are not replaced here.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from folio import analytics_service as svc
from folio.analytics.lookthrough import company_key
from folio.db.models_analytics import Watchlist, WatchlistItem
from folio.db.models_insight import (
    InstrumentAlias,
    NewsCluster,
    NewsItem,
    NewsLink,
    NewsSource,
)
from folio.db.models_ledger import Instrument, Listing
from folio.lookthrough.service import latest_snapshots
from folio.news.cluster import WINDOW, ClusterState, Member, best_cluster
from folio.news.linking import (
    MIN_KEY_LENGTH,
    AliasRule,
    ConstituentRule,
    Hit,
    Matcher,
    Subject,
    is_macro_story,
    relevance,
)
from folio.news.normalize import title_tokens
from folio.news.service import refresh_effect
from folio.strategies import service as strategies
from folio.strategies.inputs import sleeve_of_instruments

ZERO = Decimal(0)
HUNDRED = Decimal(100)
TOP_CONSTITUENTS = 150  # per ETF: the names a story is most likely to be about
LLM_PREFIX = "llm:"


@dataclass
class World:
    """What links are made against, read once per run."""

    matcher: Matcher
    exposure: dict[int, Decimal]  # instrument id -> share of the portfolio
    sleeve_exposure: dict[str, Decimal]
    macro_sleeves: dict[str, set[str]]  # macro series code -> sleeves watching it


@dataclass(frozen=True)
class Result:
    items: int  # newly clustered
    new_clusters: int
    links: int  # links written


def ensure_aliases(db: Session, instrument_ids: list[int]) -> None:
    """Every instrument gets one alias from its own name (for a share: "asml" from "ASML
    Holding N.V."), which feedback can lower. The owner may add others."""
    have = set(db.scalars(select(InstrumentAlias.instrument_id)))
    for instrument in db.scalars(select(Instrument).where(Instrument.id.in_(instrument_ids))):
        if instrument.id in have:
            continue
        phrase = " ".join(company_key(instrument.name, None).split())
        if len(phrase) >= MIN_KEY_LENGTH:
            db.add(InstrumentAlias(instrument_id=instrument.id, alias=phrase, weight=Decimal(1)))
    db.flush()


def build_world(db: Session, today: datetime) -> World:
    day = today.date()
    ctx = svc.get_context(db, day)
    exposure: dict[int, Decimal] = defaultdict(lambda: ZERO)
    total = ZERO
    if not ctx.empty:
        for h in ctx.points[ctx.index(day)].holdings:
            if h.value_eur is not None and h.quantity > 0:
                exposure[h.instrument_id] += h.value_eur
                total += h.value_eur
    shares = {i: (v / total if total else ZERO) for i, v in exposure.items()}
    watched = {
        i
        for i in db.scalars(
            select(WatchlistItem.instrument_id)
            .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
            .where(Watchlist.deleted_at.is_(None))
        )
    }
    ids = sorted(set(shares) | watched)
    ensure_aliases(db, ids)

    subjects: list[Subject] = []
    instruments = {
        i.id: i
        for i in db.scalars(
            select(Instrument).where(Instrument.id.in_(ids), Instrument.deleted_at.is_(None))
        )
    }
    listings: dict[int, Listing] = {}
    for row in db.scalars(
        select(Listing)
        .where(Listing.instrument_id.in_(ids))
        .order_by(Listing.pricing_primary.desc(), Listing.id.desc())
    ):
        listings[row.instrument_id] = row
    for i, instrument in instruments.items():
        listing = listings.get(i)
        subjects.append(
            Subject(
                instrument_id=i,
                name=instrument.name,
                isin=instrument.isin,
                ticker=None if listing is None else listing.ticker,
                eodhd_symbol=None
                if listing is None
                else (listing.provider_symbols or {}).get("eodhd"),
                exposure=shares.get(i, ZERO),
            )
        )
    aliases = [
        AliasRule(a.instrument_id, a.alias, a.weight)
        for a in db.scalars(select(InstrumentAlias).where(InstrumentAlias.instrument_id.in_(ids)))
    ]
    constituents: list[ConstituentRule] = []
    for etf_id, snap in latest_snapshots(db, list(instruments), on=day).items():
        ranked = sorted(snap.constituents, key=lambda c: c.weight_pct, reverse=True)
        for c in ranked[:TOP_CONSTITUENTS]:
            constituents.append(
                ConstituentRule(
                    etf_id,
                    " ".join(company_key(c.name, None).split()),
                    c.isin,
                    c.name,
                    c.weight_pct,
                )
            )

    sleeve_exposure: dict[str, Decimal] = {}
    macro_sleeves: dict[str, set[str]] = defaultdict(set)
    for _strategy, _version, definition in strategies.running(db):
        mapping = sleeve_of_instruments(db, definition)
        for spec in definition.sleeves:
            sleeve_exposure.setdefault(
                spec.id,
                sum((shares.get(i, ZERO) for i, s in mapping.items() if s == spec.id), ZERO),
            )
            for key in spec.watch:
                if key in definition.macro_series:
                    macro_sleeves[definition.macro_series[key].code].add(spec.id)
        for rule in definition.rules:
            if rule.type != "macro_threshold" or not rule.enabled:
                continue
            code = definition.macro_series[rule.series].code
            macro_sleeves[code] |= set(rule.applies_to)
    return World(
        Matcher(subjects, aliases, constituents), shares, sleeve_exposure, dict(macro_sleeves)
    )


def _text(item: NewsItem) -> str:
    return f"{item.title}. {item.summary}"


def _hits(world: World, item: NewsItem) -> list[Hit]:
    return world.matcher.match(_text(item), item.symbols or ())


def cluster_and_link(db: Session, now: datetime) -> Result:
    items = list(
        db.scalars(
            select(NewsItem).where(NewsItem.cluster_id.is_(None)).order_by(NewsItem.published_at)
        )
    )
    if not items:
        return Result(0, 0, 0)
    world = build_world(db, now)
    sources = {s.id: s for s in db.scalars(select(NewsSource))}

    floor = items[0].published_at - WINDOW
    states: list[ClusterState] = []
    rows: dict[int, NewsCluster] = {}
    for cluster in db.scalars(select(NewsCluster).where(NewsCluster.last_seen >= floor)):
        rows[cluster.id] = cluster
        members = [
            _member(world, i)
            for i in db.scalars(select(NewsItem).where(NewsItem.cluster_id == cluster.id))
        ]
        states.append(ClusterState(cluster.id, members))

    touched: set[int] = set()
    created = 0
    for item in items:
        member = _member(world, item)
        state = best_cluster(member, states)
        if state is None:
            row = NewsCluster(
                title=item.title, first_seen=item.published_at, last_seen=item.published_at
            )
            db.add(row)
            db.flush()
            rows[row.id] = row
            state = ClusterState(row.id, [])
            states.append(state)
            created += 1
        state.members.append(member)
        assert state.id is not None  # noqa: S101 - set above or loaded from the table
        item.cluster_id = state.id
        row = rows[state.id]
        row.first_seen, row.last_seen = state.first_seen, state.last_seen
        touched.add(state.id)
    db.flush()

    links = 0
    for cluster_id in touched:
        links += _relink(db, world, sources, rows[cluster_id], now)
    db.flush()
    return Result(len(items), created, links)


def _member(world: World, item: NewsItem) -> Member:
    return Member(
        tokens=title_tokens(item.title),
        entities=frozenset(str(h.instrument_id) for h in _hits(world, item)),
        published=item.published_at,
        content_hash=item.content_hash,
    )


def _relink(
    db: Session, world: World, sources: dict[int, NewsSource], cluster: NewsCluster, now: datetime
) -> int:
    """Rebuild a cluster's deterministic links from all of its items."""
    best: dict[tuple[int | None, str | None, str], NewsLink] = {}

    def keep(link: NewsLink) -> None:
        key = (link.instrument_id, link.sleeve, link.link_type)
        old = best.get(key)
        if old is None or link.relevance > old.relevance:
            best[key] = link

    for item in db.scalars(select(NewsItem).where(NewsItem.cluster_id == cluster.id)):
        source = sources.get(item.source_id)
        trust = source.trust_weight if source is not None else Decimal("0.5")
        age = now - item.published_at
        for hit in _hits(world, item):
            share = world.exposure.get(hit.instrument_id, ZERO)
            if hit.kind == "look_through":
                share = share * (hit.weight_pct or ZERO) / HUNDRED
            keep(
                NewsLink(
                    cluster_id=cluster.id,
                    instrument_id=hit.instrument_id,
                    link_type=hit.kind,
                    weight_pct=hit.weight_pct,
                    relevance=relevance(hit.kind, share, trust, age, hit.alias_weight),
                    matched_by=hit.matched_by,
                )
            )
        if source is not None and source.macro_series and is_macro_story(_text(item)):
            for code in source.macro_series:
                for sleeve in sorted(world.macro_sleeves.get(code, ())):
                    keep(
                        NewsLink(
                            cluster_id=cluster.id,
                            sleeve=sleeve,
                            link_type="macro",
                            relevance=relevance(
                                "macro", world.sleeve_exposure.get(sleeve, ZERO), trust, age
                            ),
                            matched_by=f"macro:{code}",
                        )
                    )
    db.execute(
        delete(NewsLink).where(
            NewsLink.cluster_id == cluster.id, ~NewsLink.matched_by.startswith(LLM_PREFIX)
        )
    )
    db.add_all(best.values())
    cluster.linked = True
    cluster.relevance = max((link.relevance for link in best.values()), default=ZERO)
    refresh_effect(db, cluster)
    return len(best)
