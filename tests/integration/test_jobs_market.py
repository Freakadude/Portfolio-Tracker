"""Market-data jobs (FR-MD-02, FR-MD-03, FR-MD-04) and the job runner."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import Account
from folio.db.models_ledger import FxRate, JobRun, LedgerTransaction, PriceBar
from folio.jobs.market import backfill_job, eod_job, fx_job, gap_job
from folio.jobs.runner import run_job
from folio.marketdata.base import Bar, ProviderError
from folio.marketdata.fake import FakeProvider
from tests.marketdata_helpers import Scripted, bars_for, make_ctx, make_listing, respond

D = Decimal
TRADING_DAY = date(2025, 12, 23)


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


def runs(db) -> list[JobRun]:  # type: ignore[no-untyped-def]
    db.expire_all()
    return list(db.scalars(select(JobRun).order_by(JobRun.id)))


def test_no_fetch_attempts_on_christmas_day(settings: Settings, db) -> None:  # type: ignore[no-untyped-def]
    make_listing(db)
    db.commit()
    provider = FakeProvider(name="primary", error=AssertionError("must not be called"))
    result = eod_job(make_ctx(settings, [provider]), "XETR", day=date(2025, 12, 25))
    assert provider.calls == []  # FR-MD-02: nothing is requested on a closed day
    assert result.status == "ok" and "closed on 2025-12-25" in result.log
    run = runs(db)[0]
    assert (run.job, run.status, run.params) == ("eod", "ok", {"mic": "XETR", "day": "2025-12-25"})


def test_eod_job_stores_closes_for_that_exchanges_listings_only(settings: Settings, db) -> None:  # type: ignore[no-untyped-def]
    _, sxr8 = make_listing(db, ticker="SXR8", mic="XETR")
    _, cspx = make_listing(db, ticker="CSPX", mic="XAMS", isin="IE0000000001")
    db.commit()
    window = bars_for("XETR", date(2025, 12, 10), TRADING_DAY)
    provider = FakeProvider(name="primary", bars={sxr8.id: window, cspx.id: window})
    result = eod_job(make_ctx(settings, [provider]), "XETR", day=TRADING_DAY)
    assert result.status == "ok" and "SXR8" in result.log
    assert provider.calls == [("eod", sxr8.id)]  # Amsterdam has its own job
    db.expire_all()
    rows = db.scalars(select(PriceBar)).all()
    assert rows and {r.listing_id for r in rows} == {sxr8.id}
    assert max(r.date for r in rows) == TRADING_DAY


def test_one_failing_listing_fails_the_run_but_not_the_others(settings: Settings, db) -> None:  # type: ignore[no-untyped-def]
    _, good = make_listing(db, ticker="GOOD")
    make_listing(db, ticker="BAD", isin="IE0000000001", symbols={})  # no symbol for any provider
    db.commit()
    provider = FakeProvider(
        name="primary", bars={good.id: bars_for("XETR", date(2025, 12, 10), TRADING_DAY)}
    )
    provider_calls = provider.calls
    result = eod_job(make_ctx(settings, [provider]), "XETR", day=TRADING_DAY)
    assert result.status == "failed"
    assert "ERROR BAD" in result.log and "GOOD:" in result.log
    db.expire_all()
    assert db.scalars(select(PriceBar)).first() is not None  # GOOD's closes were kept
    assert runs(db)[0].status == "failed" and runs(db)[0].finished_at is not None
    assert ("eod", good.id) in provider_calls


def test_manual_and_archived_instruments_are_not_fetched(settings: Settings, db) -> None:  # type: ignore[no-untyped-def]
    make_listing(db, ticker="PRIV", manual=True, isin=None, symbols={})
    make_listing(db, ticker="OLD", status="archived", isin="IE0000000001")
    db.commit()
    provider = FakeProvider(name="primary")
    result = eod_job(make_ctx(settings, [provider]), "XETR", day=TRADING_DAY)
    assert provider.calls == [] and result.status == "ok"


def test_backfill_reaches_back_to_the_first_purchase(settings: Settings, db) -> None:  # type: ignore[no-untyped-def]
    instrument, listing = make_listing(db)
    account = Account(name="A")
    db.add(account)
    db.flush()
    db.add(
        LedgerTransaction(
            account_id=account.id, instrument_id=instrument.id, type="buy",
            trade_date=date(2023, 6, 15), quantity=D(1), price=D(400),
        )
    )  # fmt: skip
    db.commit()
    provider = FakeProvider(
        name="primary", bars={listing.id: bars_for("XETR", date(2023, 6, 1), date(2024, 1, 12))}
    )
    ctx = make_ctx(settings, [provider], now=datetime(2024, 1, 12, 18, 0, tzinfo=UTC))
    result = backfill_job(ctx, listing.id)
    assert result.status == "ok"
    assert provider.ranges == [(date(2023, 6, 8), date(2024, 1, 12))]  # a week before the buy
    db.expire_all()
    first = db.scalars(select(PriceBar).order_by(PriceBar.date)).first()
    assert first is not None and first.date <= date(2023, 6, 15)  # history covers the purchase


def test_backfill_without_transactions_defaults_to_a_year(settings: Settings, db) -> None:  # type: ignore[no-untyped-def]
    _, listing = make_listing(db)
    db.commit()
    provider = FakeProvider(
        name="primary", bars={listing.id: bars_for("XETR", date(2023, 1, 2), date(2024, 1, 12))}
    )
    backfill_job(
        make_ctx(settings, [provider], now=datetime(2024, 1, 12, 18, 0, tzinfo=UTC)), listing.id
    )
    assert provider.ranges == [(date(2023, 1, 12), date(2024, 1, 12))]


def test_backfill_of_a_vanished_listing_is_reported(settings: Settings, db) -> None:  # type: ignore[no-untyped-def]
    result = backfill_job(make_ctx(settings, []), 999)
    assert result.status == "failed" and "Listing 999 no longer exists" in result.log


def test_gap_job_repairs_missing_days(settings: Settings, db) -> None:  # type: ignore[no-untyped-def]
    _, listing = make_listing(db)
    full = bars_for("XETR", date(2024, 1, 2), date(2024, 1, 12))
    db.add_all(
        PriceBar(listing_id=listing.id, date=b.date, close=b.close, source="primary")
        for b in full
        if b.date != date(2024, 1, 9)
    )
    db.commit()
    provider = FakeProvider(name="primary", bars={listing.id: full})
    ctx = make_ctx(settings, [provider], now=datetime(2024, 1, 15, 12, 0, tzinfo=UTC))
    result = gap_job(ctx)
    assert result.status == "ok" and "1 gaps, 0 left" in result.log
    db.expire_all()
    assert db.scalar(select(PriceBar).where(PriceBar.date == date(2024, 1, 9))) is not None


def test_fx_job_fetches_rates_for_currencies_in_use(settings: Settings, db) -> None:  # type: ignore[no-untyped-def]
    make_listing(db, ticker="AAA", currency="USD", isin="IE0000000001")
    db.commit()
    ecb = Scripted(lambda r: respond("ecb_exr.csv", content_type="text/csv"))
    ctx = make_ctx(settings, [], ecb=ecb, now=datetime(2025, 1, 6, 17, 0, tzinfo=UTC))
    result = fx_job(ctx)
    assert result.status == "ok" and "USD" in result.log
    db.expire_all()
    assert {r.currency for r in db.scalars(select(FxRate))} == {"USD"}  # only what is in use
    assert fx_job(ctx).status == "ok"  # a second run is harmless
    assert db.query(FxRate).count() == 9


def test_fx_job_with_only_euro_holdings_does_nothing(settings: Settings, db) -> None:  # type: ignore[no-untyped-def]
    make_listing(db)
    db.commit()
    ecb = Scripted(lambda r: respond("ecb_exr.csv"))
    result = fx_job(make_ctx(settings, [], ecb=ecb))
    assert "nothing to fetch" in result.log and ecb.requests == []


def test_a_crashing_job_is_recorded_and_does_not_escape(settings: Settings, db) -> None:  # type: ignore[no-untyped-def]
    ctx = make_ctx(settings, [])

    def explode(session, log):  # type: ignore[no-untyped-def]
        log.info("started")
        raise ProviderError("provider exploded")

    result = run_job(ctx, "boom", explode, {"x": 1})
    assert result.status == "failed" and "provider exploded" in result.log
    row = runs(db)[0]
    assert (row.job, row.status, row.params) == ("boom", "failed", {"x": 1})
    assert row.started_at <= row.finished_at  # type: ignore[operator]


def test_bars_stored_by_a_failed_run_are_rolled_back(settings: Settings, db) -> None:  # type: ignore[no-untyped-def]
    _, listing = make_listing(db)
    db.commit()
    ctx = make_ctx(settings, [])

    def half_done(session, log):  # type: ignore[no-untyped-def]
        session.add(PriceBar(listing_id=listing.id, date=date(2024, 1, 2), close=D(1), source="x"))
        session.flush()
        raise RuntimeError("crash after writing")

    run_job(ctx, "half", half_done)
    db.expire_all()
    assert db.scalars(select(PriceBar)).first() is None
    assert Bar  # keep the import used by type checkers


def test_fx_job_with_two_currencies_does_not_lock_on_the_call_counter(
    settings: Settings,
    db,  # type: ignore[no-untyped-def]
) -> None:
    """Regression: each ECB call is charged through its own connection, so the job must not
    hold an open write transaction between calls ("database is locked")."""
    from folio.jobs.context import JobContext
    from folio.marketdata.ecb import EcbRates
    from folio.marketdata.fallback import ProviderChain
    from folio.marketdata.runtime import make_usage_tracker
    from tests.marketdata_helpers import client

    make_listing(db, ticker="AAA", currency="USD", isin="IE0000000001")
    make_listing(db, ticker="BBB", currency="GBP", isin="IE0000000002")
    db.commit()
    factory = make_session_factory(make_engine(settings.db_url))
    usage = make_usage_tracker(factory)
    ecb = Scripted(lambda r: respond("ecb_exr.csv", content_type="text/csv"))
    ctx = JobContext(
        session_factory=factory,
        chain_for=lambda session: ProviderChain([]),
        ecb_for=lambda session: EcbRates(client("ecb", ecb, usage=usage)),
        now=lambda: datetime(2025, 1, 6, 17, 0, tzinfo=UTC),
    )
    result = fx_job(ctx)
    assert result.status == "ok", result.log
    assert usage.usage_today() == {"ecb": 2}  # one counted call per currency
    db.expire_all()
    assert {r.currency for r in db.scalars(select(FxRate))} == {"USD", "GBP"}
