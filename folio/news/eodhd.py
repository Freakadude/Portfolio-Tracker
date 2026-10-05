"""EODHD's news endpoint, read into the same items as a feed (FR-NW-01).

EODHD returns the article text in `content`; only the first 500 characters of it are kept as the
summary, like a feed's description (FR-NW-03). The tickers it tags the article with are kept as
hints for linking.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from folio.news.feed import FeedItem
from folio.news.normalize import canonical_url, clean_title, plain_text


def _moment(text: Any, now: datetime) -> datetime:
    try:
        moment = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return now
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return min(moment.astimezone(UTC), now + timedelta(hours=1))


def parse_eodhd_news(rows: Any, now: datetime) -> list[FeedItem]:
    if not isinstance(rows, list):
        return []
    items: dict[str, FeedItem] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = clean_title(row.get("title"))
        link = str(row.get("link") or "").strip()
        if not title or not link.startswith(("http://", "https://")):
            continue
        url = canonical_url(link)
        symbols = tuple(str(s) for s in (row.get("symbols") or []) if isinstance(s, str))[:20]
        items.setdefault(
            url,
            FeedItem(
                title,
                plain_text(row.get("content")),
                url,
                _moment(row.get("date"), now),
                symbols,
            ),
        )
    return sorted(items.values(), key=lambda i: (i.published, i.url))
