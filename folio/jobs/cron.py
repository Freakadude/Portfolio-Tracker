# ruff: noqa: E501  (the table of jobs reads best one job to a line)
"""The scheduled jobs the owner may move to another time (FR-SY-09), and the cron text they are
written in. Light on purpose: the settings schema imports it to check what is saved."""

from __future__ import annotations

from dataclasses import dataclass

from apscheduler.triggers.cron import CronTrigger

LOCAL_TZ = "Europe/Amsterdam"


@dataclass(frozen=True)
class JobInfo:
    job_id: str
    title: str
    what: str  # what it does, in words for the owner
    normal: str  # when it normally runs, in words
    cron: str  # the normal schedule as 5-field cron text (used to show and reset)
    tz: str = LOCAL_TZ


JOBS: tuple[JobInfo, ...] = (
    JobInfo("fx", "Exchange rates", "Fetches the ECB's euro exchange rates and the ECB deposit rate, so values in other currencies can be turned into euro.", "every day at 16:30", "30 16 * * *"),
    JobInfo("gaps", "Price gap check", "Looks for trading days in the last 30 days that have no closing price and fetches them again.", "every day at 22:00", "0 22 * * *"),
    JobInfo("snapshots", "Value snapshots", "Saves the day's portfolio value and positions, which the charts and returns are built on.", "every day at 23:00", "0 23 * * *"),
    JobInfo("rules", "Strategy rules", "Checks your strategy's rules against the portfolio and raises alerts.", "every day at 23:15", "15 23 * * *"),
    JobInfo("outcomes", "Advice follow-up", "Compares past recommendations with what the prices did since (7, 30 and 90 days).", "every day at 23:30", "30 23 * * *"),
    JobInfo("macro", "Macro series", "Fetches the economic indicator series (FRED and ECB) you chose.", "every day at 07:00", "0 7 * * *"),
    JobInfo("news", "News check", "Looks for new stories at your news sources. Each source also keeps to its own interval.", "every 15 minutes from 07:00 to 22:45, hourly overnight", "*/15 7-22 * * *"),
    JobInfo("quotes", "Delayed quotes", "Fetches delayed intraday prices for what you hold or watch while its market is open.", "every 15 minutes (UTC)", "*/15 * * * *", "UTC"),
    JobInfo("backup", "Backup", "Makes a backup of the database (without your API keys) and removes old ones.", "every day at 03:00", "0 3 * * *"),
    JobInfo("retention", "Clean-up", "Deletes old quotes, events and logs according to your retention settings.", "every day at 03:30", "30 3 * * *"),
    JobInfo("calendar", "Event calendar", "Refreshes central bank dates and, if switched on, earnings dates.", "Mondays at 06:30", "30 6 * * mon"),
    JobInfo("event_briefs", "Event briefs", "Writes the evening brief for tomorrow's events (it waits for 18:00 itself).", "every 15 minutes from 18:00 to 23:45", "*/15 18-23 * * *"),
    JobInfo("lookthrough", "ETF holdings refresh", "Fetches the holdings of ETFs that have a download address or EODHD set up.", "the 1st of each month at 06:00", "0 6 1 * *"),
    JobInfo("quarterly_review", "Quarterly review", "Writes the review of your strategy after a quarter ends.", "the 1st of January, April, July and October at 08:00", "0 8 1 1,4,7,10 *"),
    JobInfo("actions", "Corporate actions", "Looks for splits and dividends on what you hold and proposes them.", "Sundays at 09:00", "0 9 * * sun"),
)  # fmt: skip

OVERRIDABLE = {j.job_id: j for j in JOBS}


def parse_cron(expression: str, tz: str = LOCAL_TZ) -> CronTrigger:
    """A schedule from 5-field cron text: minute, hour, day of month, month, weekday. Weekdays
    are written as names (mon-fri) because numbers mean different days in different tools."""
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError(
            "A schedule has 5 parts: minute, hour, day of month, month and weekday, for example "
            "30 19 * * mon-fri."
        )
    if any(c.isdigit() for c in fields[4]):
        raise ValueError("Write the weekday as a name, such as mon-fri or sun, not as a number.")
    try:
        return CronTrigger.from_crontab(expression, timezone=tz)
    except ValueError as exc:
        raise ValueError(f"This is not a valid schedule: {exc}") from exc
