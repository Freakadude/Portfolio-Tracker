"""Delayed quotes within the budget (FR-MD-05), retention (FR-SY-09) and the ECB deposit rate
used as the risk-free rate (FR-PF-06)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from folio.analytics_service import clear_cache, risk_free_rate
from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models_analytics import AppEvent, MacroPoint, Quote
from folio.db.models_ledger import PriceBar
from folio.events import prune_events, publish_event
from folio.jobs.context import JobContext
from folio.jobs.market import eod_job, fx_job, quotes_job, retention_job
from folio.marketdata import exchanges
from folio.marketdata.base import ProviderError
from folio.marketdata.base import Quote as ProviderQuote
from folio.marketdata.budget import UsageTracker
from folio.marketdata.ecb import EcbRates
from folio.marketdata.fake import FakeProvider
from folio.marketdata.fallback import ProviderChain
from folio.marketdata.macro import DEPOSIT_RATE, MacroService
from tests.conftest import PASSWORD, USERNAME
from tests.marketdata_helpers import Scripted, bars_for, client, make_ctx, make_listing, respond

D = Decimal
OPEN = datetime(2024, 1, 9, 10, 0, tzinfo=UTC)  # a Tuesday, 11:00 in Frankfurt
NIGHT = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


@pytest.fixture
def api(client: TestClient, owner: None) -> TestClient:
    client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return client


def hold(api: TestClient, db, instrument_id: int) -> None:  # type: ignore[no-untyped-def]
    db.commit()
    account = api.post("/api/v1/accounts", json={"name": "Degiro"}).json()["id"]
    r = api.post(
        "/api/v1/transactions",
        json={
            "account_id": account,
            "instrument_id": instrument_id,
            "type": "buy",
            "trade_date": "2024-01-02",
            "quantity": "10",
            "price": "100",
        },
    )
    assert r.status_code == 201, r.text


def quotes(db) -> list[Quote]:  # type: ignore[no-untyped-def]
    db.expire_all()
    return list(db.scalars(select(Quote).order_by(Quote.id)))


# --- market hours -------------------------------------------------------------------------------


def test_the_exchange_calendar_knows_when_a_market_is_open() -> None:
    assert exchanges.is_open("XETR", OPEN)
    assert not exchanges.is_open("XETR", NIGHT)  # after 17:30 Frankfurt time
    assert not exchanges.is_open("XETR", datetime(2024, 1, 13, 10, 0, tzinfo=UTC))  # Saturday
    assert not exchanges.is_open("XETR", datetime(2025, 12, 25, 10, 0, tzinfo=UTC))  # Christmas
    assert not exchanges.is_open("XETR", datetime(1990, 1, 9, 10, 0, tzinfo=UTC))  # before the data
    assert exchanges.is_open("XNYS", datetime(2024, 1, 9, 15, 0, tzinfo=UTC))  # 10:00 in New York


# --- the quote job ------------------------------------------------------------------------------


def test_quotes_are_stored_for_held_listings_on_open_markets_only(api, db, settings) -> None:  # type: ignore[no-untyped-def]
    held, held_listing = make_listing(db, ticker="HELD")
    _, watched = make_listing(db, ticker="WATCH", isin="IE0000000001")
    _, closed = make_listing(db, ticker="NYSE", mic="XNYS", currency="USD", isin="IE0000000002")
    hold(api, db, held.id)
    provider = FakeProvider(
        name="fake",
        quotes={
            held_listing.id: ProviderQuote(D("101.5"), OPEN - timedelta(minutes=15)),
            watched.id: ProviderQuote(D("9"), OPEN),
            closed.id: ProviderQuote(D("9"), OPEN),
        },
    )
    result = quotes_job(make_ctx(settings, [provider], now=OPEN))
    assert result.status == "ok" and "1 new quote(s) for 1 listing(s) (fake)" in result.log
    assert provider.calls == [("quotes", 1)]  # only what is held, only an open market
    [row] = quotes(db)
    assert (row.listing_id, row.price, row.source) == (held_listing.id, D("101.5"), "fake")


def test_an_unchanged_quote_is_not_stored_twice(api, db, settings) -> None:  # type: ignore[no-untyped-def]
    held, listing = make_listing(db, ticker="HELD")
    hold(api, db, held.id)
    stamp = OPEN - timedelta(minutes=15)
    provider = FakeProvider(quotes={listing.id: ProviderQuote(D("101.5"), stamp)})
    ctx = make_ctx(settings, [provider], now=OPEN)
    quotes_job(ctx)
    quotes_job(ctx)
    assert len(quotes(db)) == 1


def test_nothing_is_asked_when_every_market_is_closed(api, db, settings) -> None:  # type: ignore[no-untyped-def]
    held, _ = make_listing(db, ticker="HELD")
    hold(api, db, held.id)
    provider = FakeProvider(error=AssertionError("must not be called"))
    result = quotes_job(make_ctx(settings, [provider], now=NIGHT), only_if_open=True)
    assert result.status == "skipped" and provider.calls == []
    from folio.db.models_ledger import JobRun

    assert db.scalars(select(JobRun).where(JobRun.job == "quotes")).first() is None  # no noise


def test_a_failing_provider_falls_back_to_the_next_for_quotes(api, db, settings) -> None:  # type: ignore[no-untyped-def]
    held, listing = make_listing(db, ticker="HELD")
    hold(api, db, held.id)
    broken = FakeProvider(name="primary", error=ProviderError("down"))
    backup = FakeProvider(name="backup", quotes={listing.id: ProviderQuote(D("100.2"), OPEN)})
    quotes_job(make_ctx(settings, [broken, backup], now=OPEN))
    assert [(q.price, q.source) for q in quotes(db)] == [(D("100.2"), "backup")]


# --- the budget reserve: quotes never cost the nightly closes -----------------------------------


def budget_ctx(settings: Settings, provider: FakeProvider, limit: int, used: int) -> JobContext:
    factory = make_session_factory(make_engine(settings.db_url))
    usage = UsageTracker(factory, lambda name: limit, today=lambda: OPEN.date())
    for _ in range(used):
        usage.charge(provider.name)
    return JobContext(
        session_factory=factory,
        chain_for=lambda session: ProviderChain([provider]),
        ecb_for=lambda session: EcbRates(client("ecb", Scripted(lambda r: httpx.Response(404)))),
        now=lambda: OPEN,
        usage=usage,
    )


def test_quotes_pause_before_the_budget_the_nightly_closes_need_is_touched(
    api, db, settings
) -> None:  # type: ignore[no-untyped-def]
    held, listing = make_listing(db, ticker="HELD")
    hold(api, db, held.id)
    provider = FakeProvider(quotes={listing.id: ProviderQuote(D("101"), OPEN)})
    # a limit of 10 with 5 used: 5 left, but one listing needs 1 + a margin of 5 for the closes
    paused = quotes_job(budget_ctx(settings, provider, limit=10, used=5))
    assert "kept for the nightly closes" in paused.log and quotes(db) == []
    assert provider.calls == []


def test_quotes_run_while_the_budget_has_room(api, db, settings) -> None:  # type: ignore[no-untyped-def]
    held, listing = make_listing(db, ticker="HELD")
    hold(api, db, held.id)
    provider = FakeProvider(quotes={listing.id: ProviderQuote(D("101"), OPEN)})
    result = quotes_job(budget_ctx(settings, provider, limit=100, used=5))
    assert "1 new quote(s)" in result.log and len(quotes(db)) == 1


def test_the_nightly_closes_still_run_when_quotes_are_paused(api, db, settings) -> None:  # type: ignore[no-untyped-def]
    held, listing = make_listing(db, ticker="HELD")
    hold(api, db, held.id)
    day = date(2024, 1, 9)
    provider = FakeProvider(
        quotes={listing.id: ProviderQuote(D("101"), OPEN)},
        bars={listing.id: bars_for("XETR", date(2024, 1, 1), day)},
    )
    ctx = budget_ctx(settings, provider, limit=10, used=5)
    quotes_job(ctx)  # paused
    result = eod_job(ctx, "XETR", day=day)
    assert result.status == "ok"
    db.expire_all()
    assert db.scalar(select(PriceBar).where(PriceBar.date == day)) is not None  # FR-MD-05


def test_a_provider_without_a_daily_limit_is_always_used(api, db, settings) -> None:  # type: ignore[no-untyped-def]
    held, listing = make_listing(db, ticker="HELD")
    hold(api, db, held.id)
    provider = FakeProvider(quotes={listing.id: ProviderQuote(D("101"), OPEN)})
    result = quotes_job(budget_ctx(settings, provider, limit=0, used=50))  # 0 = unlimited
    assert "1 new quote(s)" in result.log


# --- positions show the delayed quote -----------------------------------------------------------


def test_a_position_carries_a_newer_delayed_quote_with_its_time(api, db, settings) -> None:  # type: ignore[no-untyped-def]
    held, listing = make_listing(db, ticker="HELD")
    for bar in bars_for("XETR", date(2024, 1, 1), date(2024, 1, 8)):
        db.add(PriceBar(listing_id=listing.id, date=bar.date, close=bar.close, source="x"))
    hold(api, db, held.id)
    provider = FakeProvider(quotes={listing.id: ProviderQuote(D("109.5"), OPEN)})
    quotes_job(make_ctx(settings, [provider], now=OPEN))

    rows = api.get("/api/v1/positions").json()["positions"]  # valued as of today
    price = rows[0]["price"]
    assert D(price["delayed_price"]) == D("109.5") and price["delayed_source"] == "fake"
    assert price["delayed_at"].startswith("2024-01-09T10:00")
    assert price["date"] == "2024-01-08"  # the close it is newer than
    assert D(rows[0]["market_value_eur"]) == 10 * D(price["close"])  # values stay end-of-day

    older = api.get("/api/v1/positions", params={"as_of": "2024-01-08"}).json()["positions"]
    assert older[0]["price"]["delayed_price"] is None  # a past date never shows today's quote


# --- retention ----------------------------------------------------------------------------------


def test_the_retention_job_prunes_old_quotes_and_events(api, db, settings) -> None:  # type: ignore[no-untyped-def]
    _, listing = make_listing(db, ticker="HELD")
    now = datetime(2024, 1, 20, 12, 0, tzinfo=UTC)
    db.add_all(
        [
            Quote(listing_id=listing.id, ts=now - timedelta(days=8), price=D(1), source="x"),
            Quote(listing_id=listing.id, ts=now - timedelta(days=2), price=D(2), source="x"),
        ]
    )
    old = publish_event(db, "price_update")
    old.ts = now - timedelta(days=2)
    publish_event(db, "price_update").ts = now - timedelta(hours=1)
    db.commit()
    result = retention_job(make_ctx(settings, [], now=now))
    assert result.status == "ok" and "1 old quote(s) and 1 old event(s)" in result.log
    assert [q.price for q in quotes(db)] == [D(2)]
    assert len(db.scalars(select(AppEvent)).all()) == 1
    assert prune_events(db, now) == 0


# --- the ECB deposit rate ------------------------------------------------------------------------


def ecb_answer(request: httpx.Request) -> httpx.Response:
    name = "ecb_dfr.csv" if "/FM/" in str(request.url) else "ecb_exr.csv"
    return respond(name, content_type="text/csv")


def test_the_fx_job_stores_the_deposit_rate_and_the_risk_free_rate_follows_it(db, settings) -> None:  # type: ignore[no-untyped-def]
    ctx = make_ctx(
        settings, [], ecb=Scripted(ecb_answer), now=datetime(2024, 6, 14, 17, 0, tzinfo=UTC)
    )
    result = fx_job(ctx)
    assert result.status == "ok" and "deposit facility rate: 7 new or changed" in result.log
    assert fx_job(ctx).status == "ok"  # idempotent
    db.expire_all()
    assert len(db.scalars(select(MacroPoint)).all()) == 7
    service = MacroService(db)
    assert service.value_on(DEPOSIT_RATE, date(2024, 6, 11)) == D("4")
    assert service.value_on(DEPOSIT_RATE, date(2024, 6, 12)) == D("3.75")  # the cut
    assert service.value_on(DEPOSIT_RATE, date(2024, 6, 1)) is None  # before what is stored
    assert risk_free_rate(db, date(2024, 6, 11)) == D("0.04")
    assert risk_free_rate(db, date(2024, 6, 13)) == D("0.0375")
    assert risk_free_rate(db, date(2024, 1, 1)) == D("0.02")  # nothing stored then: the fixed one


def test_a_fixed_risk_free_rate_can_be_chosen(api, db, settings) -> None:  # type: ignore[no-untyped-def]
    fx_job(make_ctx(settings, [], ecb=Scripted(ecb_answer), now=datetime(2024, 6, 14, tzinfo=UTC)))
    r = api.put(
        "/api/v1/settings/analytics",
        json={"risk_free_source": "fixed", "risk_free_fixed_pct": "1.5"},
        headers={"X-CSRF-Token": api.cookies.get("folio_csrf") or ""},
    )
    assert r.status_code == 200, r.text
    db.expire_all()
    assert risk_free_rate(db, date(2024, 6, 13)) == D("0.015")


def test_a_failing_deposit_rate_fetch_fails_the_run_but_keeps_the_exchange_rates(
    db, settings
) -> None:  # type: ignore[no-untyped-def]
    make_listing(db, ticker="AAA", currency="USD", isin="IE0000000001")
    db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        if "/FM/" in str(request.url):
            return httpx.Response(500, text="boom")
        return respond("ecb_exr.csv", content_type="text/csv")

    ctx = make_ctx(settings, [], ecb=Scripted(handler), now=datetime(2025, 1, 6, 17, 0, tzinfo=UTC))
    result = fx_job(ctx)
    assert result.status == "failed" and "deposit facility rate" in result.log
    from folio.db.models_ledger import FxRate

    db.expire_all()
    assert db.scalars(select(FxRate)).first() is not None


def test_risk_reports_the_stored_deposit_rate(api, db, settings) -> None:  # type: ignore[no-untyped-def]
    clear_cache()
    fund, listing = make_listing(db, ticker="F")
    for bar in bars_for("XETR", date(2024, 6, 3), date(2024, 6, 14)):
        db.add(PriceBar(listing_id=listing.id, date=bar.date, close=bar.close, source="x"))
    db.commit()
    account = api.post("/api/v1/accounts", json={"name": "A"}).json()["id"]
    body: dict[str, Any] = {
        "account_id": account,
        "instrument_id": fund.id,
        "type": "buy",
        "trade_date": "2024-06-03",
        "quantity": "10",
        "price": "100",
    }
    assert api.post("/api/v1/transactions", json=body).status_code == 201
    fx_job(make_ctx(settings, [], ecb=Scripted(ecb_answer), now=datetime(2024, 6, 14, tzinfo=UTC)))
    r = api.get("/api/v1/portfolio/risk", params={"window": "MAX", "as_of": "2024-06-14"})
    assert r.status_code == 200, r.text
    assert D(r.json()["risk_free"]) == D("0.0375")
