"""Turning feeds into stored items (FR-NW-02, FR-NW-03): canonical links, plain-text summaries
of at most 500 characters, and RSS or Atom read into items. The ECB and Federal Reserve feeds
are recorded from the live sites on 2026-10-05."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from folio.news.feed import FeedError, parse_feed
from folio.news.normalize import (
    SUMMARY_LIMIT,
    canonical_url,
    clean_title,
    content_hash,
    plain_text,
    title_tokens,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "news"
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# --- links ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "canonical"),
    [
        ("http://www.Example.com/a/b/?utm_source=x&b=2&a=1#top", "https://example.com/a/b?a=1&b=2"),
        ("https://example.com/story//part//2", "https://example.com/story/part/2"),
        ("https://example.com:443/x?fbclid=abc&id=7", "https://example.com/x?id=7"),
        ("https://example.com:8443/x", "https://example.com:8443/x"),
        ("https://example.com", "https://example.com/"),
        ("  https://example.com/x/  ", "https://example.com/x"),
    ],
)
def test_a_link_has_one_canonical_form(url: str, canonical: str) -> None:
    assert canonical_url(url) == canonical


def test_the_same_story_by_two_links_is_one_link() -> None:
    a = canonical_url("https://www.ecb.europa.eu//press/key/date/2026/html/ecb.sp261005.en.html")
    b = canonical_url("http://ecb.europa.eu/press/key/date/2026/html/ecb.sp261005.en.html?utm_x=1")
    assert a == b == "https://ecb.europa.eu/press/key/date/2026/html/ecb.sp261005.en.html"


# --- text -----------------------------------------------------------------------------------------


def test_markup_becomes_plain_text_without_scripts() -> None:
    html = "<p>Rates &amp; <b>yields</b></p><script>alert(1)</script><style>p{}</style>  <br>Next"
    assert plain_text(html) == "Rates & yields Next"
    assert plain_text(None) == "" and plain_text("") == ""


def test_a_summary_is_cut_at_a_word_within_the_limit() -> None:
    text = "word " * 400
    cut = plain_text(text)
    assert len(cut) <= SUMMARY_LIMIT and cut.endswith("…")
    assert cut[:-1].split(" ")[-1] == "word"  # never in the middle of a word
    assert plain_text("short") == "short"
    assert len(plain_text("x" * 900)) == SUMMARY_LIMIT  # one long word is cut hard


def test_titles_are_cleaned_and_compared_by_meaning() -> None:
    assert clean_title("  ECB holds   rates \n") == "ECB holds rates"
    assert content_hash("ECB holds rates.") == content_hash("ecb HOLDS rates")
    assert content_hash("ECB holds rates") != content_hash("ECB cuts rates")
    assert title_tokens("The ECB holds rates, says Lagarde") == {"ecb", "holds", "rates", "lagarde"}


# --- feeds ----------------------------------------------------------------------------------------


def test_the_recorded_ecb_feed_is_read() -> None:
    items = parse_feed(load("ecb_press.xml"), NOW)
    assert len(items) == 15
    assert [i.published for i in items] == sorted(i.published for i in items)  # oldest first
    newest = items[-1]
    assert newest.title == "Philip R. Lane: Diagnostic Challenges for ECB Monetary Policy"
    assert newest.published == datetime(2026, 10, 5, 8, 0, tzinfo=UTC)  # 10:00 +0200
    # the feed writes "//press/..."; the stored link has one slash and no www
    assert newest.url.startswith("https://ecb.europa.eu/press/key/date/2026/")
    assert newest.summary == ""  # the ECB sends headlines only
    assert all(len(i.title) <= 300 and len(i.summary) <= SUMMARY_LIMIT for i in items)


def test_the_recorded_fed_feed_uses_its_description_as_the_summary() -> None:
    items = parse_feed(load("fed_press_all.xml"), NOW)
    assert len(items) == 8
    first = items[-1]
    assert first.title.startswith("Federal Reserve Board announces")
    assert first.summary.startswith("Federal Reserve Board announces")
    assert first.published == datetime(2026, 10, 2, 20, 45, tzinfo=UTC)
    assert first.url.startswith("https://federalreserve.gov/newsevents/pressreleases/")


def test_an_atom_feed_is_read_and_unusable_entries_are_left_out() -> None:
    items = parse_feed(load("atom_example.xml"), NOW)
    assert [i.title for i in items] == [
        "Distribution announced",
        "Index change for the Example Semiconductor UCITS ETF",
    ]  # the entry whose link is not http(s) is dropped
    distribution, index = items
    assert distribution.url == "https://issuer.example/notices/2026/distribution"
    assert distribution.published == datetime(2026, 9, 30, 6, 30, tzinfo=UTC)  # 08:30 +0200
    assert index.url == "https://issuer.example/notices/2026/semis-index-change"  # no utm, no #top
    assert (
        index.summary == "The fund will track a new index from 1 November."
    )  # no markup, no script


def test_something_that_is_not_a_feed_is_explained() -> None:
    with pytest.raises(FeedError, match="does not return an RSS or Atom feed"):
        parse_feed(b"<html><body><h1>Welcome</h1></body></html>", NOW)
    with pytest.raises(FeedError):
        parse_feed(b"", NOW)


def test_a_date_in_the_future_is_not_taken_at_face_value() -> None:
    rss = (
        b'<rss version="2.0"><channel><title>t</title><item><title>Soon</title>'
        b"<link>https://x.example/a</link><pubDate>Mon, 05 Oct 2027 10:00:00 GMT</pubDate>"
        b"</item></channel></rss>"
    )
    (item,) = parse_feed(rss, NOW)
    assert item.published <= NOW.replace(hour=13)


def test_the_same_link_twice_in_a_feed_is_one_item() -> None:
    rss = (
        b'<rss version="2.0"><channel><title>t</title>'
        b"<item><title>One</title><link>https://x.example/a?utm_source=1</link></item>"
        b"<item><title>One again</title><link>https://www.x.example/a/</link></item>"
        b"</channel></rss>"
    )
    assert len(parse_feed(rss, NOW)) == 1
