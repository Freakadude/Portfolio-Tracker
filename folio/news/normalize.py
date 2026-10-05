"""Turning feed items into the small, comparable records Folio stores (FR-NW-03).

Only a headline, a short summary, a link and metadata are kept; article bodies never are. A link
is reduced to one canonical form (no tracking parameters, no fragment, no duplicate slashes) so
the same story reached by two links is stored once.
"""

from __future__ import annotations

import hashlib
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SUMMARY_LIMIT = 500
TITLE_LIMIT = 300
URL_LIMIT = 500

_TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "igshid", "yclid", "_hsenc",
    "_hsmi", "ref", "ref_src", "cmpid", "cid", "campaign", "spm", "ocid", "ito", "ns_campaign",
}  # fmt: skip
_SPACES = re.compile(r"\s+")
_WORDS = re.compile(r"[a-z0-9]+")
STOP_WORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "to",
        "in",
        "on",
        "for",
        "and",
        "or",
        "at",
        "by",
        "with",
        "from",
        "as",
        "is",
        "are",
        "was",
        "be",
        "its",
        "it",
        "this",
        "that",
        "after",
        "before",
        "over",
        "under",
        "new",
        "says",
        "say",
        "said",
    ]
)


class _Text(HTMLParser):
    """Collects the text of a fragment of HTML, ignoring scripts and styles."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("br", "p", "li", "div"):
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def plain_text(markup: str | None, limit: int = SUMMARY_LIMIT) -> str:
    """Markup to one line of plain text of at most `limit` characters, cut at a word."""
    if not markup:
        return ""
    parser = _Text()
    parser.feed(markup)
    parser.close()
    text = _SPACES.sub(" ", unescape("".join(parser.parts))).strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:.-")
    return (cut or text[: limit - 1]) + "…"


def canonical_url(url: str) -> str:
    """The one form of a link used to recognise a story: https for http, no `www.`, no default
    port, no fragment, no tracking parameters, repeated slashes collapsed, no trailing slash."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    port = f":{parts.port}" if parts.port and parts.port not in (80, 443) else ""
    path = re.sub(r"/{2,}", "/", parts.path) or "/"
    if len(path) > 1:
        path = path.rstrip("/")
    query = urlencode(
        sorted(
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
        )
    )
    scheme = "https" if parts.scheme in ("http", "https") else parts.scheme
    return urlunsplit((scheme, host + port, path, query, ""))[:URL_LIMIT]


def title_tokens(title: str) -> frozenset[str]:
    """The words of a headline that carry its meaning, for comparing stories."""
    return frozenset(w for w in _WORDS.findall(title.lower()) if w not in STOP_WORDS and len(w) > 1)


def clean_title(title: str | None) -> str:
    return plain_text(title, TITLE_LIMIT)


def content_hash(title: str) -> str:
    """The same headline from another source or link hashes alike."""
    words = " ".join(sorted(_WORDS.findall(title.lower())))
    return hashlib.sha256(words.encode("utf-8")).hexdigest()
