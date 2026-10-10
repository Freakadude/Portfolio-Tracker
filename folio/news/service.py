"""News sources and stored items (FR-NW-01, FR-NW-02, FR-NW-03).

Sources are the owner's list. Some come ready (Q12, widened in ADR 0062: central banks,
regulators and official filings, issuers, EODHD and Nasdaq.com headlines): the ECB's and the
Federal Reserve's press releases and the Fed's speeches, each tied to the macro series it speaks
to, US export-control rules, EODHD's news for the held tickers, Nasdaq.com headlines per holding
and the SEC filings of held and watched companies. Issuer feeds are added by the owner.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.audit import write_audit
from folio.db.models_insight import NewsAssessment, NewsCluster, NewsItem, NewsLink, NewsSource
from folio.news.feed import FeedItem
from folio.news.fetch import backoff
from folio.news.normalize import content_hash
from folio.settings_store import get_value, set_value

KINDS = ("rss", "eodhd", "sec")
SYMBOL = "{symbol}"  # in an RSS address: read once per followed holding
TRUST_MIN, TRUST_MAX = Decimal("0.1"), Decimal("1")
SEEDED_KEY = "news.defaults_seeded"
ADDED_KEY = "news.defaults_added"  # names of the ready-made sources already added
# the ready-made sources of the first version, added before the names were kept
FIRST_DEFAULTS = (
    "ECB press releases",
    "Federal Reserve press releases",
    "EODHD news for your tickers",
)

DEFAULTS: tuple[dict[str, object], ...] = (
    {
        "name": "ECB press releases",
        "url": "https://www.ecb.europa.eu/rss/press.html",
        "trust_weight": Decimal("1"),
        "poll_minutes": 60,
        "macro_series": ["ECB_DFR"],
    },
    {
        "name": "Federal Reserve press releases",
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "trust_weight": Decimal("1"),
        "poll_minutes": 60,
        "macro_series": ["DFF", "DFII10", "DTWEXBGS"],
    },
    {
        "name": "EODHD news for your tickers",
        "kind": "eodhd",
        "url": "",
        "trust_weight": Decimal("0.7"),
        "poll_minutes": 360,
        "macro_series": [],
    },
    # ADR 0062
    {
        "name": "Federal Reserve speeches and testimony",
        "url": "https://www.federalreserve.gov/feeds/speeches_and_testimony.xml",
        "trust_weight": Decimal("1"),
        "poll_minutes": 60,
        "macro_series": ["DFF", "DFII10", "DTWEXBGS"],
    },
    {
        "name": "US export controls (BIS, Federal Register)",
        "url": "https://www.federalregister.gov/api/v1/documents.rss"
        "?conditions%5Bagencies%5D%5B%5D=industry-and-security-bureau",
        "trust_weight": Decimal("1"),
        "poll_minutes": 360,
        "macro_series": [],
    },
    {
        "name": "SEC filings for your holdings",
        "kind": "sec",
        "url": "",
        "trust_weight": Decimal("1"),
        "poll_minutes": 180,
        "macro_series": [],
    },
    {
        "name": "Nasdaq.com headlines for your shares",
        "url": "https://www.nasdaq.com/feed/rssoutbound?symbol={symbol}",
        "trust_weight": Decimal("0.5"),
        "poll_minutes": 180,
        "macro_series": [],
    },
)


class SourceError(ValueError):
    """The source cannot be saved; the message is for the owner."""


@dataclass(frozen=True)
class SourceInput:
    name: str
    kind: str = "rss"
    url: str = ""
    language: str = "en"
    trust_weight: Decimal = Decimal("0.7")
    poll_minutes: int = 60
    enabled: bool = True
    macro_series: Sequence[str] = ()


def check(data: SourceInput) -> SourceInput:
    name = data.name.strip()
    if not name or len(name) > 100:
        raise SourceError("Give the source a name of up to 100 characters.")
    if data.kind not in KINDS:
        raise SourceError("The kind must be rss, eodhd or sec.")
    if data.kind == "rss":
        parts = urlsplit(data.url.strip())
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise SourceError("The feed address must start with http:// or https://.")
    if not TRUST_MIN <= data.trust_weight <= TRUST_MAX:
        raise SourceError("Trust must be between 0.1 and 1.")
    if not 15 <= data.poll_minutes <= 1440:
        raise SourceError("Check the feed every 15 minutes to once a day (15 to 1440 minutes).")
    language = data.language.strip().lower()
    if not 2 <= len(language) <= 5 or not language.replace("-", "").isalpha():
        raise SourceError("The language is a code such as en or nl.")
    return SourceInput(
        name,
        data.kind,
        data.url.strip(),
        language,
        data.trust_weight,
        data.poll_minutes,
        data.enabled,
        [c.strip() for c in data.macro_series if c.strip()],
    )


def seed_defaults(db: Session) -> None:
    """Add each ready-made source once, also the ones that came with a later version. A default
    the owner deletes does not come back: what was added is kept by name."""
    added = list(get_value(db, ADDED_KEY, None) or [])
    if not added and get_value(db, SEEDED_KEY, False):
        added = list(FIRST_DEFAULTS)  # an install from before the names were kept
    missing = [spec for spec in DEFAULTS if spec["name"] not in added]
    if not missing:
        return
    for spec in missing:
        db.add(
            NewsSource(
                name=str(spec["name"]),
                kind=str(spec.get("kind", "rss")),
                url=str(spec["url"]),
                language="en",
                trust_weight=Decimal(str(spec["trust_weight"])),
                poll_minutes=int(str(spec["poll_minutes"])),
                enabled=True,
                macro_series=list(spec["macro_series"]),  # type: ignore[call-overload]
            )
        )
    set_value(db, ADDED_KEY, added + [str(spec["name"]) for spec in missing])
    set_value(db, SEEDED_KEY, True)
    db.flush()


def list_sources(db: Session) -> list[NewsSource]:
    seed_defaults(db)
    return list(
        db.scalars(
            select(NewsSource).where(NewsSource.deleted_at.is_(None)).order_by(NewsSource.id)
        )
    )


def get_source(db: Session, source_id: int) -> NewsSource:
    source = db.get(NewsSource, source_id)
    if source is None or source.deleted_at is not None:
        raise SourceError("That source does not exist.")
    return source


def _snapshot(source: NewsSource) -> dict[str, object]:
    return {
        "name": source.name,
        "kind": source.kind,
        "url": source.url,
        "language": source.language,
        "trust_weight": str(source.trust_weight),
        "poll_minutes": source.poll_minutes,
        "enabled": source.enabled,
        "macro_series": list(source.macro_series or []),
    }


def create_source(db: Session, data: SourceInput, actor: str = "user") -> NewsSource:
    seed_defaults(db)
    ok = check(data)
    source = NewsSource(
        name=ok.name,
        kind=ok.kind,
        url=ok.url,
        language=ok.language,
        trust_weight=ok.trust_weight,
        poll_minutes=ok.poll_minutes,
        enabled=ok.enabled,
        macro_series=list(ok.macro_series),
    )
    db.add(source)
    db.flush()
    write_audit(db, actor, "news_source", "create", entity_id=source.id, diff=_snapshot(source))
    return source


def update_source(
    db: Session, source_id: int, data: SourceInput, actor: str = "user"
) -> NewsSource:
    source = get_source(db, source_id)
    ok = check(data)
    before = _snapshot(source)
    url_changed = source.url != ok.url
    source.name, source.kind, source.url = ok.name, ok.kind, ok.url
    source.language, source.trust_weight = ok.language, ok.trust_weight
    source.poll_minutes, source.enabled = ok.poll_minutes, ok.enabled
    source.macro_series = list(ok.macro_series)
    if url_changed:  # a new address starts from scratch
        source.etag = source.last_modified = source.last_error = None
        source.failures, source.next_fetch_at = 0, None
    after = _snapshot(source)
    diff = {k: {"old": before[k], "new": after[k]} for k in after if before[k] != after[k]}
    if diff:
        write_audit(db, actor, "news_source", "update", entity_id=source.id, diff=diff)
    return source


def delete_source(db: Session, source_id: int, now: datetime, actor: str = "user") -> None:
    source = get_source(db, source_id)
    source.deleted_at, source.enabled = now, False
    write_audit(db, actor, "news_source", "delete", entity_id=source.id, diff=_snapshot(source))


def due_sources(db: Session, now: datetime) -> list[NewsSource]:
    return [
        s
        for s in list_sources(db)
        if s.enabled and (s.next_fetch_at is None or s.next_fetch_at <= now)
    ]


@dataclass(frozen=True)
class Stored:
    new: int
    seen: int  # already stored


def store_items(db: Session, source: NewsSource, items: Sequence[FeedItem]) -> Stored:
    """Add the items not stored yet. The link is the identity of an item (FR-NW-04 groups
    different links to one story later)."""
    urls = [i.url for i in items]
    known = set(db.scalars(select(NewsItem.canonical_url).where(NewsItem.canonical_url.in_(urls))))
    new = 0
    for item in items:
        if item.url in known:
            continue
        known.add(item.url)
        db.add(
            NewsItem(
                source_id=source.id,
                canonical_url=item.url,
                title=item.title,
                summary=item.summary,
                published_at=item.published,
                language=source.language,
                content_hash=content_hash(item.title),
                symbols=list(item.symbols) or None,
            )
        )
        new += 1
    db.flush()
    return Stored(new, len(items) - new)


def record_success(
    source: NewsSource, now: datetime, etag: str | None, last_modified: str | None
) -> None:
    source.etag, source.last_modified = etag, last_modified
    source.last_fetch_at, source.failures, source.last_error = now, 0, None
    source.next_fetch_at = now + timedelta(minutes=source.poll_minutes)


def record_failure(source: NewsSource, now: datetime, error: str) -> None:
    source.failures += 1
    source.last_error = error[:500]
    source.last_fetch_at = now
    source.next_fetch_at = now + backoff(source.poll_minutes, source.failures)


# --- does a story touch the owner at all (ADR 0061) ---------------------------------------------

LLM_PREFIX = "llm:"  # links the model added carry this in `matched_by`
SLEEVE_MIN_IMPACT = 20  # a macro story that only reaches a sleeve counts from this score


def effect_of(
    assessed: bool,
    affected: Sequence[object],
    impact: int,
    links: Sequence[tuple[int | None, str | None, str]],
) -> bool:
    """Whether the conclusion on a story is that it touches something the owner holds, watches or
    has a sleeve for. `links` are (instrument id, sleeve, matched_by) of the story. Before it is
    assessed, any link to a holding, watched instrument or sleeve counts; afterwards the
    assessment decides: it names affected holdings, or the model added a link of its own, or a
    sleeve is reached and the score is not noise. A story with none of these is not listed."""
    own = [k for k in links if k[0] is not None or k[1]]
    if not own:
        return False
    if not assessed:
        return True
    return (
        bool(affected)
        or any(k[2].startswith(LLM_PREFIX) for k in own)
        or (any(k[1] for k in own) and impact >= SLEEVE_MIN_IMPACT)
    )


def refresh_effect(db: Session, cluster: NewsCluster) -> bool:
    """Work out `affects_owner` of a story from its links and its latest assessment."""
    db.flush()
    links = [
        (k.instrument_id, k.sleeve, k.matched_by or "")
        for k in db.scalars(select(NewsLink).where(NewsLink.cluster_id == cluster.id))
    ]
    latest = db.scalars(
        select(NewsAssessment)
        .where(NewsAssessment.cluster_id == cluster.id)
        .order_by(NewsAssessment.id.desc())
    ).first()
    cluster.affects_owner = effect_of(
        cluster.assessed and latest is not None,
        [] if latest is None else list(latest.affected or []),
        0 if latest is None else latest.impact_score,
        links,
    )
    return cluster.affects_owner
