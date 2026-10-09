"""Exchanges: codes, provider symbol suffixes, trading calendars and EOD job times (FR-MD-02).

Trading days and closes come from the `exchange_calendars` library, so holidays and early
closes are never hard-coded. Trading dates are exchange-local dates (NFR-02).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

EOD_DELAY = timedelta(hours=2)  # the nightly price job runs two hours after the close
CALENDAR_START = pd.Timestamp("1999-01-04")  # the library's default would start in 2006


@dataclass(frozen=True)
class Exchange:
    mic: str
    name: str
    default_currency: str  # a guess only; real trading currencies are confirmed by a provider
    yahoo_suffix: str
    eodhd_suffix: str


EXCHANGES: dict[str, Exchange] = {
    e.mic: e
    for e in (
        Exchange("XETR", "Xetra", "EUR", ".DE", ".XETRA"),
        Exchange("XAMS", "Euronext Amsterdam", "EUR", ".AS", ".AS"),
        Exchange("XPAR", "Euronext Paris", "EUR", ".PA", ".PA"),
        Exchange("XMIL", "Borsa Italiana", "EUR", ".MI", ".MI"),
        Exchange("XLON", "London Stock Exchange", "GBP", ".L", ".LSE"),
        Exchange("XSWX", "SIX Swiss Exchange", "CHF", ".SW", ".SW"),
        Exchange("XNYS", "NYSE", "USD", "", ".US"),
        Exchange("XNAS", "Nasdaq", "USD", "", ".US"),
    )
}

# Bloomberg exchange codes as reported by OpenFIGI. Xetra appears as "GR" in its data (see
# ADR 0006); "GY" is Bloomberg's own code for it. US composite codes map to NYSE, which shares
# Nasdaq's holiday calendar.
BLOOMBERG_TO_MIC: dict[str, str] = {
    "GR": "XETR",
    "GY": "XETR",
    "NA": "XAMS",
    "FP": "XPAR",
    "IM": "XMIL",
    "LN": "XLON",
    "SW": "XSWX",
    "US": "XNYS",
    "UN": "XNYS",
    "UQ": "XNAS",
}


def exchange_for(mic: str) -> Exchange | None:
    return EXCHANGES.get(mic)


def provider_symbols(mic: str, ticker: str) -> dict[str, str]:
    """Symbols for each provider that can price this listing."""
    exchange = EXCHANGES.get(mic)
    if exchange is None:
        return {}
    return {
        "yahoo": f"{ticker}{exchange.yahoo_suffix}",
        "eodhd": f"{ticker}{exchange.eodhd_suffix}",
    }


@lru_cache(maxsize=32)
def _calendar(mic: str, year: int) -> xcals.ExchangeCalendar:
    # The year only keys the cache so a long-running worker picks up a new end date.
    return xcals.get_calendar(
        mic, start=CALENDAR_START, end=pd.Timestamp(year=year + 1, month=12, day=31)
    )


def has_calendar(mic: str) -> bool:
    return mic in EXCHANGES


def calendar(mic: str) -> xcals.ExchangeCalendar:
    return _calendar(mic, datetime.now(UTC).year)


def is_trading_day(mic: str, day: date) -> bool:
    return bool(calendar(mic).is_session(pd.Timestamp(day)))


def trading_days(mic: str, start: date, end: date) -> list[date]:
    """Sessions between two dates, inclusive, as exchange-local dates."""
    cal = calendar(mic)
    lo = max(pd.Timestamp(start), cal.first_session)
    hi = min(pd.Timestamp(end), cal.last_session)
    if lo > hi:
        return []
    return [ts.date() for ts in cal.sessions_in_range(lo, hi)]


def is_open(mic: str, at: datetime) -> bool:
    """Whether the exchange is trading at the moment `at` (timezone-aware)."""
    cal = calendar(mic)
    stamp = pd.Timestamp(at).tz_convert("UTC").floor("min")
    if stamp < cal.first_minute or stamp > cal.last_minute:
        return False
    return bool(cal.is_open_on_minute(stamp, ignore_breaks=True))


def session_over(mic: str, day: date, now: datetime) -> bool:
    """Whether the session of exchange-local `day` has finished at `now` (a day without a session
    counts as over). A close fetched before this is the price so far, not a close."""
    cal = calendar(mic)
    stamp = pd.Timestamp(day)
    if not cal.is_session(stamp):
        return True
    return bool(now >= cal.session_close(stamp).to_pydatetime())


def local_date(mic: str, at: datetime) -> date:
    """The exchange-local calendar date of a moment (UTC for a listing without a calendar)."""
    if not has_calendar(mic):
        return at.astimezone(UTC).date()
    return at.astimezone(ZoneInfo(str(calendar(mic).tz))).date()


def local_time(mic: str, at: datetime) -> datetime:
    """The exchange-local wall clock of a moment, without a zone (UTC for a listing without a
    calendar). A chart that shows these reads in market hours."""
    if not has_calendar(mic):
        return at.astimezone(UTC).replace(tzinfo=None)
    return at.astimezone(ZoneInfo(str(calendar(mic).tz))).replace(tzinfo=None)


def previous_trading_day(mic: str, day: date) -> date | None:
    """The latest session on or before `day`."""
    days = trading_days(mic, day - timedelta(days=14), day)
    return days[-1] if days else None


@dataclass(frozen=True)
class MarketHours:
    """Trading hours around a moment: today's session (None on a holiday or weekend) and the
    next time the exchange opens, all in UTC."""

    timezone: str
    open_now: bool
    opens: datetime | None  # today's session, exchange-local day
    closes: datetime | None
    next_open: datetime | None  # strictly after `now`


def market_hours(mic: str, now: datetime) -> MarketHours:
    cal = calendar(mic)
    zone = str(cal.tz)
    day = pd.Timestamp(now.astimezone(ZoneInfo(zone)).date())
    opens = closes = None
    if cal.is_session(day):
        opens = cal.session_open(day).to_pydatetime()
        closes = cal.session_close(day).to_pydatetime()
    stamp = pd.Timestamp(now).tz_convert("UTC").floor("min")
    try:
        following = cal.next_open(stamp).to_pydatetime()
    except Exception:  # noqa: BLE001 - past the end of the calendar: nothing to announce
        following = None
    return MarketHours(zone, is_open(mic, now), opens, closes, following)


def eod_job_time(mic: str, day: date) -> datetime | None:
    """When to fetch closes for `day`: two hours after the exchange closes, in exchange-local
    time. None when the exchange is closed that day (no fetch is attempted)."""
    cal = calendar(mic)
    ts = pd.Timestamp(day)
    if not cal.is_session(ts):
        return None
    close_utc: datetime = cal.session_close(ts).to_pydatetime()
    local: datetime = (close_utc + EOD_DELAY).astimezone(ZoneInfo(str(cal.tz)))
    return local


def next_eod_job_time(mic: str, now: datetime) -> datetime:
    """The next scheduled EOD fetch strictly after `now` (timezone-aware)."""
    zone = ZoneInfo(str(calendar(mic).tz))
    day = now.astimezone(zone).date()
    for _ in range(15):
        at = eod_job_time(mic, day)
        if at is not None and at > now:
            return at
        day += timedelta(days=1)
    raise RuntimeError(f"No trading day found for {mic} in the next two weeks")
