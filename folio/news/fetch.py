"""Fetching feeds politely (FR-NW-02).

- Conditional requests: the ETag and Last-Modified of the last answer are sent back, and a 304
  costs no parsing.
- robots.txt is read once a day per site and obeyed; if it cannot be read because the site is
  failing (5xx, network), the feed is not fetched this time.
- One request per site at a time, at least `min_interval` seconds apart.
- A failing source backs off: the wait doubles with each failure, up to a day.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from folio.marketdata.base import ProviderError
from folio.marketdata.http import HttpClient

MIN_INTERVAL = 10.0  # seconds between requests to one site
ROBOTS_TTL = timedelta(hours=24)
MAX_BODY = 5 * 1024 * 1024
MAX_BACKOFF = timedelta(hours=24)
AGENT_NAME = "Folio"


class RobotsDisallowed(ProviderError):
    """The site's robots.txt asks robots not to fetch this address."""


@dataclass(frozen=True)
class Fetched:
    status: str  # ok | not_modified
    body: bytes = b""
    etag: str | None = None
    last_modified: str | None = None


def backoff(poll_minutes: int, failures: int) -> timedelta:
    """How long to wait after `failures` failures in a row: the source's own interval, doubled
    for each failure, never more than a day."""
    wait: timedelta = timedelta(minutes=poll_minutes) * (2 ** max(0, failures - 1))
    return wait if wait < MAX_BACKOFF else MAX_BACKOFF


def domain_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


class Fetcher:
    """Downloads feeds. Holds the robots.txt cache and the last-request times, so keep one
    instance for the whole worker process."""

    def __init__(
        self,
        client_for: Callable[[str], HttpClient],
        *,
        clock: Callable[[], datetime],
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        min_interval: float = MIN_INTERVAL,
    ) -> None:
        self._client_for = client_for
        self._clock = clock
        self._monotonic = monotonic
        self._sleep = sleep
        self._min_interval = min_interval
        self._robots: dict[str, tuple[datetime, RobotFileParser | None]] = {}
        self._last: dict[str, float] = {}

    def _pace(self, domain: str) -> None:
        last = self._last.get(domain)
        if last is not None:
            wait = self._min_interval - (self._monotonic() - last)
            if wait > 0:
                self._sleep(wait)
        self._last[domain] = self._monotonic()

    def _rules(self, url: str) -> RobotFileParser | None:
        domain = domain_of(url)
        now = self._clock()
        cached = self._robots.get(domain)
        if cached is not None and now - cached[0] < ROBOTS_TTL:
            return cached[1]
        scheme = urlsplit(url).scheme or "https"
        self._pace(domain)
        response = self._client_for(domain).request("GET", f"{scheme}://{domain}/robots.txt")
        rules: RobotFileParser | None = None
        if response.status_code == 200:
            rules = RobotFileParser()
            rules.parse(response.text.splitlines())
        elif response.status_code >= 500:
            raise ProviderError(
                f"{domain} could not give its robots.txt (HTTP {response.status_code})."
            )
        # 4xx: there is no robots.txt, so nothing is disallowed
        self._robots[domain] = (now, rules)
        return rules

    def allowed(self, url: str) -> bool:
        rules = self._rules(url)
        return rules is None or rules.can_fetch(AGENT_NAME, url)

    def get(self, url: str, etag: str | None = None, last_modified: str | None = None) -> Fetched:
        """The feed at `url`, or "not modified" when the site says nothing changed."""
        if not self.allowed(url):
            raise RobotsDisallowed(
                f"{domain_of(url)}'s robots.txt does not allow fetching this feed."
            )
        headers: dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        domain = domain_of(url)
        self._pace(domain)
        response = self._client_for(domain).request("GET", url, headers=headers)
        if response.status_code == 304:
            return Fetched("not_modified", etag=etag, last_modified=last_modified)
        if response.status_code in (401, 403):
            raise ProviderError(f"{domain} refused the request (HTTP {response.status_code}).")
        if response.status_code == 404:
            raise ProviderError("The feed address was not found (HTTP 404). Check the address.")
        if response.status_code >= 400:
            raise ProviderError(f"{domain} returned HTTP {response.status_code}.")
        if len(response.content) > MAX_BODY:
            raise ProviderError("The feed is larger than 5 MB and was not read.")
        return Fetched(
            "ok",
            response.content,
            response.headers.get("etag"),
            response.headers.get("last-modified"),
        )
