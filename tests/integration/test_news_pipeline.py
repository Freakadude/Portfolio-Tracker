"""Clustering and linking stored news against a real book (FR-NW-04, FR-NW-05, FR-NW-10):
four sources reporting one story are one cluster; a story about an ETF's top holding links to the
ETF with its weight; a Fed rate story links to the sleeve that watches the series."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import count

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import Account
from folio.db.models_analytics import Watchlist, WatchlistItem
from folio.db.models_insight import InstrumentAlias, NewsCluster, NewsItem, NewsLink, NewsSource
from folio.db.models_ledger import PriceBar
from folio.ledger_service import TransactionIn, create_transaction
from folio.lookthrough.parse import Constituent, HoldingsRead
from folio.lookthrough.service import store_snapshot
from folio.news import service as news_service
from folio.news.normalize import content_hash
from folio.news.pipeline import cluster_and_link
from folio.strategies import service as strategies
from tests.marketdata_helpers import make_listing

D = Decimal
NOW = datetime(2024, 3, 15, 20, tzinfo=UTC)
YAML = """\
strategy:
  name: News test
  macro_series:
    US_REAL_YIELD_10Y: { source: fred, code: DFII10 }
    FED_FUNDS: { source: fred, code: DFF }
  sleeves:
    - { id: equity, members: [IE00B5BMR087, NL0010273215] }
    - { id: gold_hedge, members: [IE00B4ND3602], watch: [US_REAL_YIELD_10Y, FED_FUNDS] }
  rules:
    - { id: real_yield, type: macro_threshold, series: US_REAL_YIELD_10Y, change_bp: 50, window_days: 30, applies_to: [gold_hedge], severity: low }
"""
_urls = count(1)


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


@pytest.fixture
def book(db: Session) -> dict[str, int]:
    """World ETF 1 000 (40 %), ASML Holding 500 (20 %), a gold ETC 1 000 (40 %); the ETF holds
    5.2 % Apple and 0.8 % ASML; the strategy's gold sleeve watches the Fed funds rate."""
    world, w_listing = make_listing(db, ticker="WRLD", isin="IE00B5BMR087")
    world.name = "World ETF"
    asml, a_listing = make_listing(
        db, ticker="ASML", isin="NL0010273215", symbols={"eodhd": "ASML.AS"}
    )
    asml.name, asml.asset_class = "ASML Holding", "EQUITY"
    gold, g_listing = make_listing(db, ticker="GLD", isin="IE00B4ND3602")
    gold.name = "Gold ETC"
    day = date(2024, 1, 1)
    while day <= NOW.date():
        if day.weekday() < 5:
            for listing in (w_listing, a_listing, g_listing):
                db.add(PriceBar(listing_id=listing.id, date=day, close=D(100), source="test"))
        day += timedelta(days=1)
    account = Account(name="Broker")
    db.add(account)
    db.flush()
    for instrument, units in ((world, 10), (asml, 5), (gold, 10)):
        create_transaction(
            db,
            TransactionIn(
                account_id=account.id,
                instrument_id=instrument.id,
                type="buy",
                trade_date=date(2024, 1, 2),
                quantity=D(units),
                price=D(100),
            ),
        )
    created = strategies.create(db, strategies.read_input(YAML, None))
    strategies.set_mode(db, created, "active")
    read = HoldingsRead(
        [
            Constituent("APPLE INC", D("5.2"), "US0378331005"),
            Constituent("ASML HOLDING NV", D("0.8"), "NL0010273215"),
        ],
        D("6"),
    )
    store_snapshot(db, world.id, read, date(2024, 3, 1), "csv")
    news_service.list_sources(db)  # the ready-made sources, with the macro series they speak to
    db.commit()
    return {"world": world.id, "asml": asml.id, "gold": gold.id}


def source(db: Session, name: str, trust: str = "0.7") -> NewsSource:
    row = news_service.create_source(
        db,
        news_service.SourceInput(
            name, url=f"https://{name.lower()}.example/feed.xml", trust_weight=D(trust)
        ),
    )
    db.flush()
    return row


def story(
    db: Session, src: NewsSource, title: str, hours_ago: float = 2, summary: str = ""
) -> NewsItem:
    item = NewsItem(
        source_id=src.id,
        canonical_url=f"https://x.example/{next(_urls)}",
        title=title,
        summary=summary,
        published_at=NOW - timedelta(hours=hours_ago),
        language="en",
        content_hash=content_hash(title),
    )
    db.add(item)
    db.flush()
    return item


def links(db: Session, cluster_id: int) -> list[NewsLink]:
    db.expire_all()
    return list(
        db.scalars(
            select(NewsLink)
            .where(NewsLink.cluster_id == cluster_id)
            .order_by(NewsLink.link_type, NewsLink.id)
        )
    )


# --- clustering ---------------------------------------------------------------------------------


def test_the_same_story_from_four_sources_is_one_cluster_with_four_items(db: Session, book) -> None:
    titles = [
        "ASML raises full-year outlook on strong chip orders",
        "ASML raises 2026 outlook on strong orders",
        "ASML raises outlook on strong chip orders",
        "ASML raises outlook after strong chip orders",
    ]
    for n, title in enumerate(titles):
        story(db, source(db, f"Wire{n}"), title, hours_ago=4 - n)
    other = story(db, source(db, "Other"), "Fed leaves interest rates unchanged", hours_ago=1)
    done = cluster_and_link(db, NOW)
    db.commit()
    assert (done.items, done.new_clusters) == (5, 2)
    clusters = list(db.scalars(select(NewsCluster).order_by(NewsCluster.id)))
    sizes = sorted(
        len(list(db.scalars(select(NewsItem).where(NewsItem.cluster_id == c.id)))) for c in clusters
    )
    assert sizes == [1, 4]
    big = next(c for c in clusters if c.id != other.cluster_id)
    assert big.title.startswith("ASML raises") and big.linked is True
    assert (big.last_seen - big.first_seen) == timedelta(hours=3)


def test_a_later_item_joins_its_story_and_nothing_is_done_twice(db: Session, book) -> None:
    first = story(
        db, source(db, "WireA"), "ASML raises outlook on strong chip orders", hours_ago=10
    )
    cluster_and_link(db, NOW)
    db.commit()
    later = story(db, source(db, "WireB"), "ASML raises outlook on strong orders", hours_ago=1)
    again = cluster_and_link(db, NOW)
    db.commit()
    assert (again.items, again.new_clusters) == (1, 0)
    assert later.cluster_id == first.cluster_id
    assert cluster_and_link(db, NOW).items == 0  # nothing left to do


# --- linking ------------------------------------------------------------------------------------


def test_a_story_about_a_holding_links_directly_and_through_the_etf(db: Session, book) -> None:
    item = story(db, source(db, "WireA"), "ASML raises outlook on strong chip orders")
    cluster_and_link(db, NOW)
    db.commit()
    by_type = {(k.link_type, k.instrument_id): k for k in links(db, item.cluster_id)}
    direct = by_type[("direct", book["asml"])]
    assert direct.matched_by == "ticker:ASML" and direct.weight_pct is None
    through = by_type[("look_through", book["world"])]
    assert through.weight_pct == D("0.8") and through.matched_by.startswith("constituent:")
    assert direct.relevance > through.relevance > 0
    cluster = db.get(NewsCluster, item.cluster_id)
    assert cluster.relevance == direct.relevance


def test_a_story_about_an_etfs_top_constituent_links_to_that_etf_with_the_weight(
    db: Session, book
) -> None:
    item = story(db, source(db, "WireA"), "Apple unveils new iPhone as services revenue climbs")
    cluster_and_link(db, NOW)
    db.commit()
    (link,) = links(db, item.cluster_id)
    assert (link.instrument_id, link.link_type, link.weight_pct) == (
        book["world"],
        "look_through",
        D("5.2"),
    )
    # 40 % of the portfolio x 5.2 % inside the ETF is about 2 % of the portfolio
    assert D("0.1") < link.relevance < D("0.3")


def test_a_fed_rate_story_links_to_the_sleeve_that_watches_the_series(db: Session, book) -> None:
    fed = db.scalar(select(NewsSource).where(NewsSource.name == "Federal Reserve press releases"))
    rates = story(db, fed, "Federal Reserve issues FOMC statement: interest rates unchanged")
    approval = story(
        db, fed, "Federal Reserve Board announces approval of application by Fleur Capital"
    )
    cluster_and_link(db, NOW)
    db.commit()
    (macro,) = links(db, rates.cluster_id)
    assert (macro.link_type, macro.sleeve, macro.instrument_id) == ("macro", "gold_hedge", None)
    assert macro.matched_by in ("macro:DFF", "macro:DFII10")
    assert links(db, approval.cluster_id) == []  # not about rates or currency: no link
    assert db.get(NewsCluster, approval.cluster_id).relevance == 0
    assert db.get(NewsCluster, approval.cluster_id).linked is True


def test_a_source_that_speaks_to_no_series_makes_no_macro_links(db: Session, book) -> None:
    item = story(db, source(db, "Wire"), "Federal Reserve issues FOMC statement")
    cluster_and_link(db, NOW)
    db.commit()
    assert links(db, item.cluster_id) == []


def test_a_watched_instrument_is_linked_with_little_weight(db: Session, book) -> None:
    extra, _ = make_listing(db, ticker="NVDA", isin="US67066G1040")
    extra.name, extra.asset_class = "Nvidia Corp", "EQUITY"
    watchlist = Watchlist(name="Ideas")
    db.add(watchlist)
    db.flush()
    db.add(WatchlistItem(watchlist_id=watchlist.id, instrument_id=extra.id))
    db.commit()
    watched = story(db, source(db, "WireA"), "Nvidia results beat estimates")
    held = story(db, source(db, "WireB"), "ASML wins record order from foundry")
    cluster_and_link(db, NOW)
    db.commit()
    (w_link,) = [k for k in links(db, watched.cluster_id) if k.link_type == "direct"]
    h_link = next(k for k in links(db, held.cluster_id) if k.link_type == "direct")
    assert w_link.instrument_id == extra.id and 0 < w_link.relevance < h_link.relevance


def test_an_alias_switched_off_by_feedback_no_longer_matches(db: Session, book) -> None:
    first = story(db, source(db, "WireA"), "asml raises outlook")  # lower case: no ticker match
    cluster_and_link(db, NOW)
    db.commit()
    alias = db.scalar(select(InstrumentAlias).where(InstrumentAlias.instrument_id == book["asml"]))
    assert alias.alias == "asml" and alias.weight == 1  # made from the instrument's own name
    assert ("direct", book["asml"]) in {
        (k.link_type, k.instrument_id) for k in links(db, first.cluster_id)
    }
    alias.weight = D("0.2")  # below the floor of 0.3
    second = story(db, source(db, "WireB"), "asml lifts guidance", hours_ago=100)
    cluster_and_link(db, NOW)
    db.commit()
    direct = [k for k in links(db, second.cluster_id) if k.link_type == "direct"]
    assert direct == []


def test_links_made_by_the_llm_are_kept_when_the_deterministic_ones_are_redone(
    db: Session, book
) -> None:
    first = story(
        db, source(db, "WireA"), "ASML raises outlook on strong chip orders", hours_ago=10
    )
    cluster_and_link(db, NOW)
    db.add(
        NewsLink(
            cluster_id=first.cluster_id,
            link_type="theme",
            sleeve="equity",
            relevance=D("0.3"),
            matched_by="llm:semiconductors",
        )
    )
    db.commit()
    story(db, source(db, "WireB"), "ASML raises outlook on strong orders", hours_ago=1)
    cluster_and_link(db, NOW)  # the cluster is relinked with its new item
    db.commit()
    kinds = {(k.link_type, k.matched_by.split(":")[0]) for k in links(db, first.cluster_id)}
    assert ("theme", "llm") in kinds and ("direct", "ticker") in kinds


def test_an_eodhd_ticker_tag_is_a_direct_link(db: Session, book) -> None:
    item = story(db, source(db, "Wire"), "Chip equipment makers rally")
    item.symbols = ["ASML.AS"]
    cluster_and_link(db, NOW)
    db.commit()
    direct = next(k for k in links(db, item.cluster_id) if k.link_type == "direct")
    assert (direct.instrument_id, direct.matched_by) == (book["asml"], "eodhd:ASML.AS")


def test_a_trusted_source_counts_for_more(db: Session, book) -> None:
    low = story(db, source(db, "Blog", "0.2"), "ASML raises outlook")
    high = story(db, source(db, "Issuer", "1"), "ASML issues statement on shares", hours_ago=2)
    cluster_and_link(db, NOW)
    db.commit()
    a = max(k.relevance for k in links(db, low.cluster_id) if k.link_type == "direct")
    b = max(k.relevance for k in links(db, high.cluster_id) if k.link_type == "direct")
    assert b > a
