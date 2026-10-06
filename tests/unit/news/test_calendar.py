"""The calendar's pure parts (FR-NW-09): the shipped central bank dates and the EODHD earnings
rows."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from folio.news.calendar import load_shipped, parse_earnings

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "providers" / "eodhd_earnings.json"


def test_the_shipped_dates_are_the_two_banks_2026_and_2027_decisions() -> None:
    events = load_shipped()
    assert len(events) == 32 and len({e.external_id for e in events}) == 32
    assert all(e.kind == "central_bank" and e.day.year in (2026, 2027) for e in events)
    for year, first_ecb, last_ecb, first_fomc, last_fomc in (
        (2026, date(2026, 2, 5), date(2026, 12, 17), date(2026, 1, 28), date(2026, 12, 9)),
        (2027, date(2027, 2, 4), date(2027, 12, 16), date(2027, 1, 27), date(2027, 12, 8)),
    ):
        ecb = sorted(e.day for e in events if e.external_id.startswith(f"ecb-{year}"))
        fomc = sorted(e.day for e in events if e.external_id.startswith(f"fomc-{year}"))
        assert len(ecb) == len(fomc) == 8
        assert (ecb[0], ecb[-1]) == (first_ecb, last_ecb)
        assert (fomc[0], fomc[-1]) == (first_fomc, last_fomc)
    # each id carries its own date, so a typo in one of them shows up here
    assert all(e.external_id.endswith(e.day.isoformat()) for e in events)
    assert {e.title for e in events} == {
        "ECB monetary policy decision",
        "Federal Reserve (FOMC) rate decision",
    }


def test_earnings_rows_are_read_and_those_without_a_report_date_are_skipped() -> None:
    import json

    rows = parse_earnings(json.loads(FIXTURE.read_text(encoding="utf-8")))
    assert [(r.code, r.report_date, r.timing) for r in rows] == [
        ("ASML.AS", date(2026, 10, 14), "BeforeMarket"),
        ("AAPL.US", date(2026, 10, 29), "AfterMarket"),
    ]
    assert rows[0].period_end == date(2026, 9, 30) and rows[0].estimate == Decimal("5.32")


@pytest.mark.parametrize("payload", [None, [], {}, {"earnings": "no"}, {"earnings": [1, {"x": 1}]}])
def test_an_unexpected_answer_gives_no_events(payload: object) -> None:
    assert parse_earnings(payload) == []
