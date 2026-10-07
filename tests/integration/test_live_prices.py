# ruff: noqa: F811
"""Quotes that survive a bad symbol, sessions that are never stored as closes, and figures that
follow the newest quote while a market is open (FR-MD-04, FR-MD-05)."""

from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
from sqlalchemy import select

from folio.db.models_analytics import Quote
from folio.db.models_ledger import PriceBar
from folio.jobs.market import quotes_job
from folio.marketdata import exchanges
from folio.marketdata.base import ListingRef
from folio.marketdata.base import Quote as ProviderQuote
from folio.marketdata.eodhd import EodhdProvider
from folio.marketdata.fake import FakeProvider
from folio.marketdata.fallback import ProviderChain
from folio.marketdata.prices import PriceService, listing_ref
from folio.marketdata.quotes import newer_quote
from folio.marketdata.yahoo import YahooProvider
from folio.portfolio import Valuation
from tests.integration.test_quotes_and_rates import NIGHT, OPEN, api, db, hold  # noqa: F401
from tests.marketdata_helpers import Scripted, bars_for, client, make_ctx, make_listing

D = Decimal
JAN_9 = date(2024, 1, 9)  # a Tuesday: Xetra trades 09:00 to 17:30 Frankfurt time (OPEN is 11:00)


def ref(listing_id: int, symbol: str) -> ListingRef:
    return ListingRef(
        listing_id, "XETR", symbol, "EUR", {"yahoo": symbol, "eodhd": symbol}, "IE00B5BMR087"
    )


# --- one unknown symbol does not cost the others their quotes -----------------------------------


def test_yahoo_skips_an_unknown_symbol_and_quotes_the_rest() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "NOPE" in str(request.url):
            return httpx.Response(404, json={})
        body = {
            "chart": {
                "result": [{"meta": {"regularMarketPrice": 12.5, "regularMarketTime": 1704794400}}]
            }
        }
        return httpx.Response(200, json=body)

    provider = YahooProvider(client("yahoo", Scripted(handler)))
    got = provider.get_quotes([ref(1, "NOPE"), ref(2, "GOOD")])
    assert set(got) == {2} and got[2].price == D("12.5")


def test_eodhd_skips_an_unknown_symbol_and_quotes_the_rest() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "NOPE" in request.url.path:
            return httpx.Response(404, json={})
        return httpx.Response(200, json={"close": 7.25, "timestamp": 1704794400})

    provider = EodhdProvider(client("eodhd", Scripted(handler)), "token")
    got = provider.get_quotes([ref(1, "NOPE"), ref(2, "GOOD")])
    assert set(got) == {2} and got[2].price == D("7.25")


def test_the_quote_job_stores_the_others_and_names_the_missing_one_without_failing(
    api,
    db,
    settings,  # noqa: F811
) -> None:  # type: ignore[no-untyped-def]
    good, good_listing = make_listing(db, ticker="GOOD")
    bad, _ = make_listing(db, ticker="CEBJ", isin="IE0000000009")
    hold(api, db, good.id)
    api.post(  # a second holding
        "/api/v1/transactions",
        json={
            "account_id": api.get("/api/v1/accounts").json()[0]["id"],
            "instrument_id": bad.id,
            "type": "buy",
            "trade_date": "2024-01-02",
            "quantity": "1",
            "price": "10",
        },
    )
    provider = FakeProvider(name="fake", quotes={good_listing.id: ProviderQuote(D("101.5"), OPEN)})
    result = quotes_job(make_ctx(settings, [provider], now=OPEN))
    assert result.status == "ok"  # a wrong symbol must not mark every 15-minute run as failed
    assert "1 new quote(s) for 2 listing(s)" in result.log and "No quote for CEBJ" in result.log
    db.expire_all()
    assert [q.listing_id for q in db.scalars(select(Quote))] == [good_listing.id]


# --- an unfinished session is not a close --------------------------------------------------------


def test_a_close_of_a_session_still_running_is_not_stored_until_it_has_finished(db) -> None:  # noqa: F811  # type: ignore[no-untyped-def]
    _, listing = make_listing(db)
    window = bars_for("XETR", date(2024, 1, 2), JAN_9)
    provider = FakeProvider(name="primary", bars={listing.id: window})
    chain = ProviderChain([provider])

    PriceService(db, chain, OPEN).update_latest(listing_ref(listing), JAN_9)  # 11:00 Frankfurt
    stored = {b.date for b in db.scalars(select(PriceBar))}
    assert JAN_9 not in stored and date(2024, 1, 8) in stored

    PriceService(db, chain, NIGHT).update_latest(listing_ref(listing), JAN_9)  # after the close
    assert JAN_9 in {b.date for b in db.scalars(select(PriceBar))}


def test_a_close_stored_too_early_is_repaired_by_the_next_update(db) -> None:  # noqa: F811  # type: ignore[no-untyped-def]
    _, listing = make_listing(db)
    window = bars_for("XETR", date(2024, 1, 2), JAN_9)
    wrong = window[-1].date  # stored while the session ran, with the price of that moment
    db.add(PriceBar(listing_id=listing.id, date=wrong, close=D("1"), source="yahoo"))
    db.flush()
    provider = FakeProvider(name="primary", bars={listing.id: window})
    PriceService(db, ProviderChain([provider]), NIGHT).update_latest(listing_ref(listing), JAN_9)
    db.expire_all()
    fixed = db.scalar(select(PriceBar).where(PriceBar.date == wrong))
    assert fixed is not None and fixed.close == window[-1].close


# --- a quote is newer than the close by the exchange's own calendar ------------------------------


def test_a_new_york_evening_quote_is_of_that_new_york_day_not_the_next_utc_day(db) -> None:  # noqa: F811  # type: ignore[no-untyped-def]
    _, listing = make_listing(db, ticker="NYSE", mic="XNYS", currency="USD", isin="IE0000000002")
    late = datetime(2024, 1, 10, 1, 30, tzinfo=UTC)  # 20:30 on 9 January in New York
    db.add(Quote(listing_id=listing.id, ts=late, price=D("50"), source="fake"))
    db.flush()
    assert exchanges.local_date("XNYS", late) == JAN_9
    assert newer_quote(db, listing, date(2024, 1, 8)) is not None
    assert newer_quote(db, listing, JAN_9) is None  # the close of that day is the price


# --- the figures follow the quote while the market is open -----------------------------------


def test_the_summary_follows_the_newest_quote_but_a_report_valuation_does_not(
    api,
    db,
    settings,  # noqa: F811
) -> None:  # type: ignore[no-untyped-def]
    held, listing = make_listing(db, ticker="HELD")
    for bar in bars_for("XETR", date(2024, 1, 1), date(2024, 1, 8)):
        db.add(PriceBar(listing_id=listing.id, date=bar.date, close=bar.close, source="x"))
    hold(api, db, held.id)  # 10 units
    provider = FakeProvider(quotes={listing.id: ProviderQuote(D("109.5"), OPEN)})
    quotes_job(make_ctx(settings, [provider], now=OPEN))

    summary = api.get("/api/v1/portfolio/summary", params={"as_of": "2024-01-09"}).json()
    assert D(summary["value_eur"]) == D("1095")  # 10 x the quote, not 10 x the close of 104
    assert D(summary["day_change"]["pnl_eur"]) == D("55")  # against the last close, 1040

    db.expire_all()
    assert Valuation.load(db).point(JAN_9).value_eur == D("1040")  # saved figures stay on closes
    assert Valuation.load(db, live=True).point(JAN_9).value_eur == D("1095")
