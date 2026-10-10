# ruff: noqa: F811  (the db fixture is imported from another test module and used as a parameter)
"""The ready-made sources of ADR 0062: they reach installs that had the first three, SEC filings
and Nasdaq.com headlines are read per held or watched company with SEC's User-Agent rule, and
what they bring links straight to the holding. Recorded responses only (2026-10-10)."""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.config import Settings
from folio.db.models import Account
from folio.db.models_analytics import Watchlist, WatchlistItem
from folio.db.models_insight import NewsItem, NewsLink, NewsSource
from folio.db.models_ledger import PriceBar
from folio.jobs.news import news_job
from folio.ledger_service import TransactionIn, create_transaction
from folio.news import service
from folio.security.secrets import SecretStore
from folio.settings_schema import NewsSettings
from folio.settings_store import save_section, set_value
from tests.conftest import PASSWORD, TEST_SECRET, USERNAME
from tests.integration.test_news import NEWS, db, job_ctx  # noqa: F401
from tests.marketdata_helpers import Scripted, make_listing

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)  # five days after ASML's Q2 filing
EMAIL = "owner@example.com"
FILING = "/Archives/edgar/data/937966/000162828026048235/form6-kquarterlyfilings.htm"


def sites(request: httpx.Request) -> httpx.Response:
    """EDGAR and Nasdaq.com as recorded; everything else is not there."""
    host, path = request.url.host, request.url.path
    if path == "/robots.txt":
        return httpx.Response(404)
    if host == "www.sec.gov" and path == "/files/company_tickers.json":
        return httpx.Response(200, content=(NEWS / "sec_company_tickers.json").read_bytes())
    if host == "data.sec.gov" and path == "/submissions/CIK0000937966.json":
        return httpx.Response(200, content=(NEWS / "sec_submissions_asml.json").read_bytes())
    if host == "www.sec.gov" and path == FILING:
        return httpx.Response(200, content=(NEWS / "sec_filing_asml_6k.htm").read_bytes())
    if host == "www.nasdaq.com" and request.url.params.get("symbol") == "ASML":
        return httpx.Response(200, content=(NEWS / "nasdaq_asml.xml").read_bytes())
    return httpx.Response(404)


def hold(db: Session, ticker: str, name: str, isin: str) -> int:
    instrument, listing = make_listing(db, ticker=ticker, mic="XAMS", isin=isin)
    instrument.name, instrument.asset_class = name, "EQUITY"
    day = date(2026, 1, 2)
    while day <= NOW.date():  # priced, so it counts as held when stories are linked
        if day.weekday() < 5:
            db.add(PriceBar(listing_id=listing.id, date=day, close=Decimal(100), source="test"))
        day += timedelta(days=1)
    account = db.scalar(select(Account)) or Account(name="Broker")
    db.add(account)
    db.flush()
    create_transaction(
        db,
        TransactionIn(
            account_id=account.id, instrument_id=instrument.id, type="buy",
            trade_date=date(2026, 1, 5), quantity=Decimal(5), price=Decimal(100),
        ),
    )  # fmt: skip
    return instrument.id


def email(db: Session, value: str = EMAIL) -> None:
    save_section(db, SecretStore(db, TEST_SECRET), "news", NewsSettings(sec_contact_email=value))
    db.commit()


@pytest.fixture
def holdings(db: Session) -> dict[str, int]:
    ids = {
        "asml": hold(db, "ASML", "ASML Holding", "NL0010273215"),
        # SAP is SAP SE's ticker at the SEC, but this holding is another company: never asked
        "clash": hold(db, "SAP", "Sapiens International", "KYG7T16G1039"),
    }
    db.commit()
    return ids


def requests_to(scripted: Scripted, host: str) -> list[httpx.Request]:
    return [r for r in scripted.requests if r.url.host == host and r.url.path != "/robots.txt"]


# --- the ready-made sources -------------------------------------------------------------------------


def test_an_install_with_the_first_three_sources_gets_the_new_ones_once(db: Session) -> None:
    for name, kind, url in (
        ("ECB press releases", "rss", "https://www.ecb.europa.eu/rss/press.html"),
        (
            "Federal Reserve press releases",
            "rss",
            "https://www.federalreserve.gov/feeds/press_all.xml",
        ),
        ("EODHD news for your tickers", "eodhd", ""),
    ):
        db.add(NewsSource(name=name, kind=kind, url=url, trust_weight=Decimal("1")))
    set_value(db, service.SEEDED_KEY, True)  # as the first version left it
    db.commit()
    names = [s.name for s in service.list_sources(db)]
    assert (
        names[3:]
        == [
            "Federal Reserve speeches and testimony",
            "US export controls (BIS, Federal Register)",
            "SEC filings for your holdings",
            "Nasdaq.com headlines for your shares",
        ]
        and len(names) == 7
    )  # the first three are not added twice
    sec_source = next(s for s in service.list_sources(db) if s.kind == "sec")
    service.delete_source(db, sec_source.id, NOW)
    db.commit()
    assert "SEC filings for your holdings" not in [s.name for s in service.list_sources(db)]


def test_a_source_kind_and_a_symbol_address_are_checked() -> None:
    ok = service.check(service.SourceInput("SEC", kind="sec"))
    assert ok.kind == "sec" and ok.url == ""
    per = service.check(service.SourceInput("Per share", url="https://news.example/rss?s={symbol}"))
    assert "{symbol}" in per.url
    with pytest.raises(service.SourceError, match="rss, eodhd or sec"):
        service.check(service.SourceInput("x", kind="ftp"))


def test_the_contact_email_is_checked() -> None:
    assert NewsSettings(sec_contact_email=" me@example.com ").sec_contact_email == "me@example.com"
    assert NewsSettings().sec_contact_email == ""
    with pytest.raises(ValidationError, match="email address"):
        NewsSettings(sec_contact_email="not an address")


# --- SEC filings and per-holding headlines ---------------------------------------------------------


def test_without_a_contact_email_sec_and_the_per_holding_headlines_wait(
    settings: Settings, db: Session, holdings: dict[str, int]
) -> None:
    scripted = Scripted(sites)
    result = news_job(job_ctx(settings, scripted, now=NOW))
    assert "SEC filings for your holdings: skipped, it needs your contact email" in result.log
    assert "Nasdaq.com headlines for your shares: skipped" in result.log
    assert requests_to(scripted, "www.sec.gov") == requests_to(scripted, "www.nasdaq.com") == []
    db.expire_all()
    waiting = db.scalar(select(NewsSource).where(NewsSource.kind == "sec"))
    assert waiting.failures == 0  # waiting for the owner is not a failure


def test_sec_filings_are_read_with_the_contact_in_the_user_agent_and_link_to_the_holding(
    settings: Settings, db: Session, holdings: dict[str, int]
) -> None:
    email(db)
    scripted = Scripted(sites)
    result = news_job(job_ctx(settings, scripted, now=NOW))
    assert "SEC filings for your holdings: 1 new" in result.log
    sec_calls = requests_to(scripted, "www.sec.gov") + requests_to(scripted, "data.sec.gov")
    assert sec_calls and all(EMAIL in r.headers["user-agent"] for r in sec_calls)
    assert [r.url.path for r in requests_to(scripted, "data.sec.gov")] == [
        "/submissions/CIK0000937966.json"  # ASML only: the SAP ticker belongs to someone else
    ]
    nasdaq = requests_to(scripted, "www.nasdaq.com")
    assert [r.url.params["symbol"] for r in nasdaq] == ["ASML"]
    assert all(EMAIL not in r.headers["user-agent"] for r in nasdaq)  # only SEC gets the address

    db.expire_all()
    source = db.scalar(select(NewsSource).where(NewsSource.kind == "sec"))
    (filing,) = db.scalars(select(NewsItem).where(NewsItem.source_id == source.id))
    assert filing.title.startswith("ASML Holding: ASML reports €9.3 billion total net sales")
    assert filing.symbols == [f"instrument:{holdings['asml']}"]
    link = db.scalar(select(NewsLink).where(NewsLink.cluster_id == filing.cluster_id))
    assert (link.instrument_id, link.link_type, link.matched_by) == (
        holdings["asml"], "direct", "feed:ASML",
    )  # fmt: skip

    headlines = db.scalar(select(NewsSource).where(NewsSource.name.like("Nasdaq%")))
    rows = db.scalars(select(NewsItem).where(NewsItem.source_id == headlines.id)).all()
    assert len(rows) == 5 and all(f"instrument:{holdings['asml']}" in r.symbols for r in rows)

    # the next run reads the list again but does not open a filing it already has
    again = Scripted(sites)
    news_job(job_ctx(settings, again, now=NOW.replace(hour=16)))
    assert FILING not in [r.url.path for r in again.requests]


def test_a_watched_company_is_followed_too(
    settings: Settings, db: Session, holdings: dict[str, int]
) -> None:
    email(db)
    tsmc, _ = make_listing(db, ticker="TSM", mic="XNYS", isin="US8740391003")
    tsmc.name = "Taiwan Semiconductor Manufacturing"
    watchlist = Watchlist(name="Ideas")
    db.add(watchlist)
    db.flush()
    db.add(WatchlistItem(watchlist_id=watchlist.id, instrument_id=tsmc.id))
    db.commit()
    scripted = Scripted(sites)
    news_job(job_ctx(settings, scripted, now=NOW))
    asked = [r.url.path for r in requests_to(scripted, "data.sec.gov")]
    assert asked == ["/submissions/CIK0000937966.json", "/submissions/CIK0001046179.json"]
    nasdaq = [r.url.params["symbol"] for r in requests_to(scripted, "www.nasdaq.com")]
    assert nasdaq == ["ASML", "TSM"]  # TSM's 404 is skipped, not a failure of the source
    db.expire_all()
    headlines = db.scalar(select(NewsSource).where(NewsSource.name.like("Nasdaq%")))
    assert headlines.failures == 0


def test_the_email_can_be_saved_in_settings(
    make_client: Callable[..., TestClient], owner: None
) -> None:
    api = make_client()
    api.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    current = api.get("/api/v1/settings/news").json()
    saved = api.put("/api/v1/settings/news", json={**current, "sec_contact_email": EMAIL})
    assert saved.status_code == 200 and saved.json()["sec_contact_email"] == EMAIL
    bad = api.put("/api/v1/settings/news", json={**current, "sec_contact_email": "nope"})
    assert bad.status_code == 422
