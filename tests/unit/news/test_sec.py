"""SEC filings read as news (ADR 0062): which company an instrument is, which filings count, and
the headline and summary, from responses recorded from EDGAR on 2026-10-10."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from folio.news import sec
from folio.news.linking import Matcher, Subject

NEWS = Path(__file__).resolve().parents[2] / "fixtures" / "news"
COMPANIES = sec.companies_from(json.loads((NEWS / "sec_company_tickers.json").read_text()))
SUBMISSIONS = json.loads((NEWS / "sec_submissions_asml.json").read_text())
FILING = (NEWS / "sec_filing_asml_6k.htm").read_bytes().decode("utf-8")
ASML = COMPANIES["ASML"]


def test_an_instrument_is_matched_by_ticker_and_name() -> None:
    assert sec.company_for(COMPANIES, "ASML", "ASML Holding N.V.") == ASML
    assert sec.company_for(COMPANIES, "ASML.AS", "ASML Holding") == ASML  # suffix dropped
    tsmc = sec.company_for(COMPANIES, "TSM", "Taiwan Semiconductor Manufacturing (ADR)")
    assert tsmc is not None and tsmc.cik == 1046179


def test_a_ticker_that_belongs_to_another_company_is_not_followed() -> None:
    assert sec.company_for(COMPANIES, "SAP", "Sapiens International") is None  # SAP SE's ticker
    assert sec.company_for(COMPANIES, "WRLD", "World ETF") is None  # not an SEC company
    assert sec.company_for(COMPANIES, None, "ASML Holding") is None


def test_only_news_bearing_filings_after_the_last_fetch_are_kept_oldest_first() -> None:
    found = sec.filings_from(SUBMISSIONS, datetime(2026, 1, 1, tzinfo=UTC))
    assert [f.form for f in found] == ["20-F", "6-K", "6-K", "6-K", "6-K"]  # no SD, at most 5
    assert [f.accepted for f in found] == sorted(f.accepted for f in found)
    recent = sec.filings_from(SUBMISSIONS, datetime(2026, 7, 1, tzinfo=UTC))
    assert [(f.form, f.accession) for f in recent] == [("6-K", "0001628280-26-048235")]
    assert sec.filings_from({"nonsense": 1}, datetime(2026, 1, 1, tzinfo=UTC)) == []


def test_the_press_release_on_the_cover_is_the_headline() -> None:
    (filing,) = sec.filings_from(SUBMISSIONS, datetime(2026, 7, 1, tzinfo=UTC))
    item = sec.item_for(7, "ASML Holding", ASML, filing, FILING)
    assert item.title.startswith("ASML Holding: ASML reports €9.3 billion total net sales")
    assert "press release dated" not in item.title
    assert item.summary.startswith("Filed with the SEC as a 6-K: ASML reports")
    assert len(item.summary) <= 400
    assert item.url == (
        "https://sec.gov/Archives/edgar/data/937966/000162828026048235/"
        "0001628280-26-048235-index.htm"
    )
    assert item.symbols == ("instrument:7",)
    assert item.published == datetime(2026, 7, 15, 10, 5, 47, tzinfo=UTC)


def test_without_a_press_release_the_form_says_what_it_is() -> None:
    found = sec.filings_from(SUBMISSIONS, datetime(2026, 1, 1, tzinfo=UTC))
    annual = sec.item_for(7, "ASML Holding", ASML, found[0], None)
    assert annual.title == "ASML Holding filed a 20-F: its annual report"
    agm = sec.item_for(7, "ASML Holding", ASML, found[1], "<p>nothing useful</p>")
    assert agm.title == "ASML Holding filed a 6-K: agm"
    results = sec.Filing("8-K", found[0].accepted, "0000320193-26-000001", "a.htm", "2.02,9.01")
    assert sec.item_for(1, "Apple", COMPANIES["AAPL"], results, None).title == (
        "Apple filed a 8-K: results of operations"
    )
    amended = sec.Filing("10-K/A", found[0].accepted, "0000320193-26-000002", "b.htm", "")
    assert "(amended): its annual report" in sec.item_for(1, "Apple", ASML, amended, None).title


def test_the_first_run_looks_back_a_month_and_later_runs_overlap_a_day() -> None:
    now = datetime(2026, 10, 10, tzinfo=UTC)
    assert sec.since_for(None, now) == datetime(2026, 9, 10, tzinfo=UTC)
    assert sec.since_for(datetime(2026, 10, 9, 12, tzinfo=UTC), now) == datetime(
        2026, 10, 8, 12, tzinfo=UTC
    )
    assert sec.user_agent(" me@example.com ") == "Folio personal portfolio tracker me@example.com"


def test_an_item_tagged_with_a_holding_links_to_it_directly() -> None:
    subject = Subject(7, "ASML Holding", "NL0010273215", "ASML", None, Decimal("0.2"))
    hits = Matcher([subject]).match("A headline that names no one", ("instrument:7",))
    assert [(h.instrument_id, h.kind, h.matched_by) for h in hits] == [(7, "direct", "feed:ASML")]
    assert Matcher([subject]).match("Nothing here", ("instrument:8",)) == []
