"""Grouping stories and linking them to holdings, without a database (FR-NW-04, FR-NW-05,
FR-NW-10)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from folio.news.cluster import ClusterState, Member, best_cluster, score, similarity
from folio.news.linking import (
    AliasRule,
    ConstituentRule,
    Matcher,
    Subject,
    is_macro_story,
    relevance,
)
from folio.news.normalize import content_hash, title_tokens

D = Decimal
T0 = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)


def member(title: str, hours: float = 0, entities: tuple[str, ...] = ()) -> Member:
    return Member(
        title_tokens(title), frozenset(entities), T0 + timedelta(hours=hours), content_hash(title)
    )


# --- clustering -------------------------------------------------------------------------------


def test_the_same_story_from_four_sources_is_one_cluster() -> None:
    titles = [
        "ASML raises full-year outlook on strong chip orders",
        "ASML raises 2026 outlook on strong orders",
        "ASML raises outlook on strong chip orders",
        "ASML raises outlook after strong chip orders",
    ]
    clusters: list[ClusterState] = []
    for n, title in enumerate(titles):
        m = member(title, hours=n)
        found = best_cluster(m, clusters)
        if found is None:
            clusters.append(ClusterState(len(clusters), [m]))
        else:
            found.members.append(m)
    assert [len(c.members) for c in clusters] == [4]


def test_different_stories_stay_apart_even_with_a_company_in_common() -> None:
    a = member("ASML raises outlook on strong chip orders", entities=("1",))
    b = member("ASML chief executive to retire next year", entities=("1",))
    assert score(a, b) is None
    unrelated = member("ECB holds interest rates steady")
    assert best_cluster(unrelated, [ClusterState(1, [a, b])]) is None


def test_a_shared_holding_lowers_the_bar_from_half_to_a_third() -> None:
    a = member("ASML raises outlook as chip orders surge")
    b = member("ASML lifts guidance, orders strong")  # one word in common besides ASML
    assert similarity(a.tokens, b.tokens) < D("0.3")
    close_a = member("Nvidia results beat estimates, shares jump after hours", entities=("7",))
    close_b = member("Nvidia results beat estimates as data centre demand grows", entities=("7",))
    plain_b = member("Nvidia results beat estimates as data centre demand grows")
    plain_a = member("Nvidia results beat estimates, shares jump after hours")
    sim = similarity(close_a.tokens, close_b.tokens)
    assert D("0.3") <= sim < D("0.5")
    assert score(close_a, close_b) == sim  # a shared entity: joins
    assert score(plain_a, plain_b) is None  # the same words, no shared entity: stays apart


def test_stories_more_than_two_days_apart_are_not_the_same_story() -> None:
    a = member("ECB holds interest rates steady", hours=0)
    assert score(a, member("ECB holds interest rates steady", hours=47)) == D(1)
    assert score(a, member("ECB holds interest rates steady", hours=49)) is None


def test_an_identical_headline_always_joins_and_the_closest_cluster_wins() -> None:
    a = member("Fed leaves rates unchanged")
    cluster_a = ClusterState(1, [a])
    cluster_b = ClusterState(2, [member("Fed leaves rates unchanged as inflation cools")])
    new = member("Fed leaves rates unchanged", hours=1)
    assert best_cluster(new, [cluster_b, cluster_a]) is cluster_a  # identical beats similar


def test_a_cluster_knows_its_first_and_last_time() -> None:
    cluster = ClusterState(1, [member("x one", 5), member("x one", 1), member("x one", 9)])
    assert (cluster.first_seen, cluster.last_seen) == (
        T0 + timedelta(hours=1),
        T0 + timedelta(hours=9),
    )


@given(st.sets(st.text("abcdef", min_size=2, max_size=4), max_size=6),
       st.sets(st.text("abcdef", min_size=2, max_size=4), max_size=6))  # fmt: skip
def test_similarity_is_symmetric_and_between_zero_and_one(a: set[str], b: set[str]) -> None:
    x, y = similarity(frozenset(a), frozenset(b)), similarity(frozenset(b), frozenset(a))
    assert x == y and 0 <= x <= 1


# --- linking ----------------------------------------------------------------------------------

ASML = Subject(1, "ASML Holding", "NL0010273215", "ASML", "ASML.AS", D("0.05"))
WORLD = Subject(2, "World ETF", "IE0000000001", "WRLD", None, D("0.40"))
F = Subject(3, "F Corp", "US0000000003", "F", None, D(0))  # a one-letter ticker
CONSTITUENTS = [
    ConstituentRule(2, "apple", "US0378331005", "APPLE INC", D("5.2")),
    ConstituentRule(2, "asml", "NL0010273215", "ASML HOLDING NV", D("0.8")),
    ConstituentRule(2, "on", None, "ON", D(1)),  # too short to match anything sensibly
]


def matcher() -> Matcher:
    return Matcher(
        [ASML, WORLD, F],
        [
            AliasRule(1, "asml", D(1)),
            AliasRule(3, "ford", D("0.2")),
            AliasRule(2, "world etf", D(1)),
        ],
        CONSTITUENTS,
    )


def kinds(text: str, symbols: tuple[str, ...] = ()) -> list[tuple[int, str, str]]:
    return [(h.instrument_id, h.kind, h.matched_by) for h in matcher().match(text, symbols)]


def test_an_isin_a_ticker_or_a_tag_links_a_story_directly() -> None:
    assert kinds("Shares of NL0010273215 jump")[0] == (1, "direct", "isin:NL0010273215")
    assert kinds("Orders lift ASML in Amsterdam")[0] == (
        1,
        "direct",
        "ticker:ASML",
    )  # beats the alias
    assert kinds("Chip stocks rally", ("asml.as",))[0] == (1, "direct", "eodhd:ASML.AS")


def test_a_name_or_alias_matches_whole_words_in_any_case() -> None:
    assert kinds("asml raises outlook") == [
        (1, "direct", "alias:asml"),
        (2, "look_through", "constituent:asml"),
    ]
    assert [h for h in kinds("The asmlfoo company") if h[0] == 1] == []  # not inside a word


def test_a_one_letter_ticker_never_matches_and_a_weak_alias_is_off() -> None:
    assert [h for h in kinds("F shares fall as Ford recalls trucks") if h[0] == 3] == []
    # the alias "ford" has weight 0.2, below the floor of 0.3: switched off by feedback


def test_a_story_about_an_etfs_top_constituent_links_to_the_etf_with_its_weight() -> None:
    hits = matcher().match("Apple unveils new iPhone as sales climb")
    assert [(h.instrument_id, h.kind, h.weight_pct, h.matched_by) for h in hits] == [
        (2, "look_through", D("5.2"), "constituent:apple")
    ]
    by_isin = matcher().match("Filing for US0378331005 shows buyback")
    assert by_isin[0].weight_pct == D("5.2")


def test_a_company_held_directly_and_inside_an_etf_links_both_ways() -> None:
    hits = matcher().match("ASML raises outlook")
    assert {(h.instrument_id, h.kind) for h in hits} == {(1, "direct"), (2, "look_through")}
    assert next(h for h in hits if h.kind == "look_through").weight_pct == D("0.8")


def test_a_short_name_is_not_a_constituent_rule() -> None:
    assert [h for h in matcher().match("Earnings on Tuesday") if h.instrument_id == 2] == []


# --- relevance ----------------------------------------------------------------------------------

FRESH = timedelta(0)


def test_relevance_follows_how_much_of_the_portfolio_a_story_touches() -> None:
    big = relevance("direct", D("0.20"), D(1), FRESH)
    small = relevance("direct", D("0.02"), D(1), FRESH)
    watched = relevance("direct", D(0), D(1), FRESH)
    assert big == D("1.0000") and big > small > watched > 0  # saturates at 10 %
    assert relevance("look_through", D("0.20"), D(1), FRESH) < big
    assert relevance("macro", D("0.20"), D(1), FRESH) == D("0.5000")


def test_relevance_is_scaled_by_trust_and_halves_each_day() -> None:
    base = relevance("direct", D("0.10"), D(1), FRESH)
    assert relevance("direct", D("0.10"), D("0.5"), FRESH) == base / 2
    assert relevance("direct", D("0.10"), D(1), timedelta(hours=24)) == base / 2
    assert relevance("direct", D("0.10"), D(1), timedelta(hours=48)) == base / 4
    assert relevance("direct", D("0.10"), D(1), FRESH, alias_weight=D("0.5")) == base / 2


@given(
    st.sampled_from(["direct", "look_through", "macro", "theme"]),
    st.decimals(min_value=0, max_value=1, places=3),
    st.decimals(min_value="0.1", max_value=1, places=2),
    st.integers(min_value=0, max_value=24 * 30),
)
def test_relevance_stays_between_zero_and_one(kind: str, exposure: D, trust: D, hours: int) -> None:
    assert 0 <= relevance(kind, exposure, trust, timedelta(hours=hours)) <= 1


def test_central_bank_rate_and_currency_news_is_told_from_the_rest() -> None:
    assert is_macro_story("Federal Reserve issues FOMC statement")
    assert is_macro_story("Monetary policy decisions: deposit facility rate unchanged")
    assert not is_macro_story(
        "Federal Reserve Board announces approval of application by Fleur Capital"
    )
    assert not is_macro_story("Federal Reserve Board announces enforcement action against bank")
