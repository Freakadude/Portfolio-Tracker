from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from folio.marketdata import exchanges

BERLIN = ZoneInfo("Europe/Berlin")


@pytest.mark.parametrize("mic", ["XETR", "XAMS", "XLON"])
def test_christmas_new_year_and_weekends_are_closed(mic: str) -> None:
    assert not exchanges.is_trading_day(mic, date(2025, 12, 25))
    assert not exchanges.is_trading_day(mic, date(2025, 1, 1))
    assert not exchanges.is_trading_day(mic, date(2025, 12, 20))  # a Saturday
    assert exchanges.is_trading_day(mic, date(2025, 12, 23))


def test_trading_days_counts_real_sessions() -> None:
    # January 2025: 23 weekdays, minus New Year's Day
    assert len(exchanges.trading_days("XETR", date(2025, 1, 1), date(2025, 1, 31))) == 22
    assert exchanges.trading_days("XETR", date(2025, 12, 24), date(2025, 12, 26)) == []


def test_calendars_reach_back_far_enough_for_old_purchases() -> None:
    # the library's default calendar starts in 2006; backfills may need earlier dates
    days = exchanges.trading_days("XETR", date(2000, 1, 3), date(2000, 1, 7))
    assert days == [date(2000, 1, d) for d in (3, 4, 5, 6, 7)]


def test_previous_trading_day_skips_closed_days() -> None:
    assert exchanges.previous_trading_day("XETR", date(2025, 12, 25)) == date(2025, 12, 23)
    assert exchanges.previous_trading_day("XETR", date(2025, 12, 23)) == date(2025, 12, 23)


def test_eod_job_runs_two_hours_after_the_close() -> None:
    xetra = exchanges.eod_job_time("XETR", date(2025, 12, 23))
    assert xetra == datetime(2025, 12, 23, 19, 30, tzinfo=BERLIN)  # closes 17:30, stored by 19:30
    assert exchanges.eod_job_time("XAMS", date(2025, 12, 23)) == datetime(
        2025, 12, 23, 19, 30, tzinfo=ZoneInfo("Europe/Amsterdam")
    )
    assert exchanges.eod_job_time("XLON", date(2025, 12, 23)) == datetime(
        2025, 12, 23, 18, 30, tzinfo=ZoneInfo("Europe/London")
    )
    assert exchanges.eod_job_time("XNYS", date(2025, 7, 1)) == datetime(
        2025, 7, 1, 18, 0, tzinfo=ZoneInfo("America/New_York")
    )


def test_no_eod_job_on_a_closed_day() -> None:
    assert exchanges.eod_job_time("XETR", date(2025, 12, 25)) is None
    assert exchanges.eod_job_time("XETR", date(2025, 12, 20)) is None


def test_next_eod_job_skips_weekends_and_holidays() -> None:
    friday_evening = datetime(2025, 12, 19, 20, 0, tzinfo=BERLIN)
    assert exchanges.next_eod_job_time("XETR", friday_evening) == datetime(
        2025, 12, 22, 19, 30, tzinfo=BERLIN
    )
    before_job = datetime(2025, 12, 22, 12, 0, tzinfo=BERLIN)
    assert exchanges.next_eod_job_time("XETR", before_job) == datetime(
        2025, 12, 22, 19, 30, tzinfo=BERLIN
    )
    christmas_eve = datetime(2025, 12, 23, 20, 0, tzinfo=BERLIN)  # 24-26 Dec are closed
    assert exchanges.next_eod_job_time("XETR", christmas_eve) == datetime(
        2025, 12, 29, 19, 30, tzinfo=BERLIN
    )
    assert exchanges.next_eod_job_time("XETR", datetime(2025, 12, 22, 5, 0, tzinfo=UTC)).tzinfo


def test_provider_symbols_follow_each_providers_convention() -> None:
    assert exchanges.provider_symbols("XETR", "SXR8") == {"yahoo": "SXR8.DE", "eodhd": "SXR8.XETRA"}
    assert exchanges.provider_symbols("XAMS", "CSPX") == {"yahoo": "CSPX.AS", "eodhd": "CSPX.AS"}
    assert exchanges.provider_symbols("XNYS", "AAPL") == {"yahoo": "AAPL", "eodhd": "AAPL.US"}
    assert exchanges.provider_symbols("MANUAL", "X") == {}


def test_openfigi_exchange_codes_map_to_mics() -> None:
    assert exchanges.BLOOMBERG_TO_MIC["GR"] == "XETR"  # how OpenFIGI reports Xetra (ADR 0006)
    assert exchanges.BLOOMBERG_TO_MIC["GY"] == "XETR"
    assert exchanges.BLOOMBERG_TO_MIC["NA"] == "XAMS"
    assert all(mic in exchanges.EXCHANGES for mic in exchanges.BLOOMBERG_TO_MIC.values())


def test_local_time_is_the_exchange_wall_clock_without_a_zone() -> None:
    winter = datetime(2024, 1, 12, 8, 15, tzinfo=UTC)
    summer = datetime(2024, 7, 12, 8, 15, tzinfo=UTC)
    assert exchanges.local_time("XETR", winter) == datetime(2024, 1, 12, 9, 15)
    assert exchanges.local_time("XETR", summer) == datetime(2024, 7, 12, 10, 15)
    assert exchanges.local_time("XLON", winter) == datetime(2024, 1, 12, 8, 15)  # GMT
    assert exchanges.local_time("XNYS", winter) == datetime(2024, 1, 12, 3, 15)  # EST
    assert exchanges.local_time("XXXX", winter) == datetime(2024, 1, 12, 8, 15)  # no calendar: UTC


def test_session_times_are_the_open_and_close_in_utc() -> None:
    xetra = exchanges.session_times("XETR", date(2024, 1, 15))
    assert xetra == (
        datetime(2024, 1, 15, 8, 0, tzinfo=UTC),
        datetime(2024, 1, 15, 16, 30, tzinfo=UTC),
    )
    newyork = exchanges.session_times(
        "XNYS", date(2024, 1, 15 + 1)
    )  # Tuesday, after Martin Luther King Day
    assert newyork is not None and newyork[0].hour == 14 and newyork[1].hour == 21
    assert exchanges.session_times("XETR", date(2024, 1, 13)) is None  # a Saturday
    assert exchanges.session_times("XNYS", date(2024, 1, 15)) is None  # a US holiday
    assert exchanges.session_times("XXXX", date(2024, 1, 15)) is None  # no calendar
