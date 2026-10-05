"""Reading an RSS or Atom feed into items (FR-NW-02, FR-NW-03).

The parsing is done by feedparser from bytes already downloaded (it never fetches anything
itself). Only the headline, a short plain-text summary, the link and the time are kept.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import feedparser

from folio.news.normalize import canonical_url, clean_title, plain_text

MAX_ITEMS = 100  # newest per fetch; a feed that sends more is not read further


class FeedError(ValueError):
    """The bytes are not a feed; the message is for the owner."""


@dataclass(frozen=True)
class FeedItem:
    title: str
    summary: str
    url: str  # canonical
    published: datetime  # UTC
    symbols: tuple[str, ...] = ()  # tickers the source tagged it with (EODHD)


def _time(entry: feedparser.FeedParserDict, now: datetime) -> datetime:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed is None:
        return now
    moment = datetime.fromtimestamp(calendar.timegm(parsed), UTC)
    return min(moment, now + timedelta(hours=1))  # a clock set in the future is not news


def parse_feed(data: bytes, now: datetime) -> list[FeedItem]:
    """The newest entries of a feed, oldest first. Raises FeedError when it is not a feed."""
    parsed = feedparser.parse(data)
    if not parsed.get("version"):  # feedparser leaves it empty for anything that is no feed
        raise FeedError(
            "That address does not return an RSS or Atom feed. Open it in a browser and look "
            "for the feed link (often marked RSS)."
        )
    items: dict[str, FeedItem] = {}
    for entry in parsed.entries[:MAX_ITEMS]:
        title = clean_title(entry.get("title"))
        link = str(entry.get("link") or "").strip()
        if not title or not link.startswith(("http://", "https://")):
            continue
        url = canonical_url(link)
        items.setdefault(
            url, FeedItem(title, plain_text(entry.get("summary")), url, _time(entry, now))
        )
    return sorted(items.values(), key=lambda i: (i.published, i.url))
