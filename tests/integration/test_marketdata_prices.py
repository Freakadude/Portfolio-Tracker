"""Price service: backfill, idempotence, overrides, gaps and staleness
(FR-MD-03, FR-MD-04, FR-MD-11, FR-INS-02)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import AuditLog
from folio.db.models_ledger import PriceBar
from folio.marketdata.base import Bar, ProviderError
from folio.marketdata.fake import FakeProvider
from folio.marketdata.fallback import AllProvidersFailed, ProviderChain
from folio.marketdata.prices import PriceService, listing_ref
from tests.marketdata_helpers import bars_for, make_listing

D = Decimal
JAN_2, JAN_12 = date(2024, 1, 2), date(2024, 1, 12)


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


def setup(db, *providers: FakeProvider):  # type: ignore[no-untyped-def]
    _, listing = make_listing(db)
    ref = listing_ref(listing)
    return PriceService(db, ProviderChain(list(providers))), ref


def stored(db, listing_id: int) -> dict[date, PriceBar]:  # type: ignore[no-untyped-def]
    rows = db.scalars(select(PriceBar).where(PriceBar.listing_id == listing_id))
    return {row.date: row for row in rows}


def test_backfill_stores_closes_with_their_source_and_is_idempotent(db) -> None:  # type: ignore[no-untyped-def]
    _, listing = make_listing(db)
    bars = bars_for("XETR", JAN_2, JAN_12)
    provider = FakeProvider(name="primary", bars={listing.id: bars})
    service, ref = PriceService(db, ProviderChain([provider])), listing_ref(listing)
    first = service.backfill(ref, JAN_2, JAN_12)
    db.commit()
    assert (first.source, first.stored) == ("primary", 9)
    rows = stored(db, listing.id)
    assert min(rows) == JAN_2 and max(rows) == JAN_12 and len(rows) == 9
    assert {r.source for r in rows.values()} == {"primary"}
    assert service.backfill(ref, JAN_2, JAN_12).stored == 0  # nothing changes on a re-run


def test_backfill_falls_back_when_the_primary_returns_nothing_and_records_the_source(db) -> None:  # type: ignore[no-untyped-def]
    _, listing = make_listing(db)
    primary = FakeProvider(name="primary", bars={})  # e.g. free plan without that history
    backup = FakeProvider(name="backup", bars={listing.id: bars_for("XETR", JAN_2, JAN_12)})
    service, ref = PriceService(db, ProviderChain([primary, backup])), listing_ref(listing)
    assert service.backfill(ref, JAN_2, JAN_12).source == "backup"
    assert {r.source for r in stored(db, listing.id).values()} == {"backup"}


def test_a_weekend_window_makes_no_provider_call(db) -> None:  # type: ignore[no-untyped-def]
    provider = FakeProvider(name="primary")
    service, ref = setup(db, provider)
    summary = service.backfill(ref, date(2024, 1, 6), date(2024, 1, 7))  # Saturday and Sunday
    assert summary.stored == 0 and provider.calls == []


def test_all_providers_failing_raises_with_reasons(db) -> None:  # type: ignore[no-untyped-def]
    service, ref = setup(db, FakeProvider(name="primary", error=ProviderError("HTTP 503")))
    with pytest.raises(AllProvidersFailed, match="primary: HTTP 503"):
        service.backfill(ref, JAN_2, JAN_12)


def test_update_latest_only_asks_for_what_is_new(db) -> None:  # type: ignore[no-untyped-def]
    _, listing = make_listing(db)
    all_bars = bars_for("XETR", JAN_2, date(2024, 1, 19))
    provider = FakeProvider(name="primary", bars={listing.id: all_bars})
    service, ref = PriceService(db, ProviderChain([provider])), listing_ref(listing)
    service.backfill(ref, JAN_2, JAN_12)
    provider.ranges.clear()
    summary = service.update_latest(ref, today=date(2024, 1, 17))
    # the newest stored close was 12 January: ask again from five days before it, in one call
    assert provider.ranges == [(date(2024, 1, 7), date(2024, 1, 17))]
    assert summary.stored == 3  # 15, 16 and 17 January; the days asked again are unchanged
    provider.ranges.clear()
    again = service.update_latest(ref, today=date(2024, 1, 17))  # already up to date
    assert provider.ranges == [(date(2024, 1, 12), date(2024, 1, 17))] and again.stored == 0


def test_update_latest_on_an_empty_listing_looks_at_the_recent_past(db) -> None:  # type: ignore[no-untyped-def]
    _, listing = make_listing(db)
    provider = FakeProvider(name="primary", bars={listing.id: bars_for("XETR", JAN_2, JAN_12)})
    service, ref = PriceService(db, ProviderChain([provider])), listing_ref(listing)
    service.update_latest(ref, today=date(2024, 1, 12))
    assert provider.ranges == [(date(2024, 1, 2), date(2024, 1, 12))]


def test_manual_override_is_audited_with_old_and_new_and_survives_refetches(db) -> None:  # type: ignore[no-untyped-def]
    _, listing = make_listing(db)
    provider = FakeProvider(name="primary", bars={listing.id: bars_for("XETR", JAN_2, JAN_12)})
    service, ref = PriceService(db, ProviderChain([provider])), listing_ref(listing)
    service.backfill(ref, JAN_2, JAN_12)
    old_close = stored(db, listing.id)[date(2024, 1, 3)].close

    row = service.set_manual_price(listing.id, date(2024, 1, 3), D("123.45"))
    db.commit()
    assert (row.close, row.source, row.overridden) == (D("123.45"), "manual", True)
    audit = db.scalars(select(AuditLog).where(AuditLog.entity == "price_bar")).one()
    assert audit.action == "override" and audit.actor == "user"
    assert audit.diff == {"close": {"old": str(old_close), "new": "123.45"}}

    assert service.store_bars(listing.id, [Bar(date(2024, 1, 3), D("999"))], "primary") == 0
    service.backfill(ref, JAN_2, JAN_12)
    db.commit()
    assert stored(db, listing.id)[date(2024, 1, 3)].close == D("123.45")  # the override stays


def test_a_hand_entered_price_for_a_new_day_is_audited_as_created(db) -> None:  # type: ignore[no-untyped-def]
    _, listing = make_listing(db, mic="MANUAL", manual=True, symbols={})
    service = PriceService(db)
    service.set_manual_price(listing.id, date(2024, 3, 1), D("50"))
    db.commit()
    audit = db.scalars(select(AuditLog)).one()
    assert audit.action == "create" and audit.diff == {"close": {"old": None, "new": "50"}}
    with pytest.raises(ValueError, match="greater than zero"):
        service.set_manual_price(listing.id, date(2024, 3, 2), D("0"))


def test_gaps_are_trading_days_without_a_close(db) -> None:  # type: ignore[no-untyped-def]
    _, listing = make_listing(db)
    bars = [b for b in bars_for("XETR", JAN_2, JAN_12) if b.date != date(2024, 1, 9)]
    service = PriceService(db, ProviderChain([]))
    ref = listing_ref(listing)
    service.store_bars(listing.id, bars, "primary")
    # the weekend of 6-7 January is not a gap; the missing Tuesday is
    assert service.detect_gaps(ref) == [date(2024, 1, 9)]


def test_gap_fill_refetches_and_reports_what_remains(db) -> None:  # type: ignore[no-untyped-def]
    _, listing = make_listing(db)
    full = bars_for("XETR", JAN_2, JAN_12)
    partial = [b for b in full if b.date not in (date(2024, 1, 4), date(2024, 1, 9))]
    provider = FakeProvider(
        name="primary", bars={listing.id: [b for b in full if b.date != date(2024, 1, 9)]}
    )  # the provider itself lacks 9 January
    service = PriceService(db, ProviderChain([provider]))
    ref = listing_ref(listing)
    service.store_bars(listing.id, partial, "primary")
    assert service.detect_gaps(ref) == [date(2024, 1, 4), date(2024, 1, 9)]
    assert service.fill_gaps(ref) == [date(2024, 1, 9)]
    assert date(2024, 1, 4) in stored(db, listing.id)


def test_no_gaps_for_hand_priced_or_empty_listings(db) -> None:  # type: ignore[no-untyped-def]
    _, manual = make_listing(db, ticker="PRIV", mic="MANUAL", manual=True, isin=None, symbols={})
    service = PriceService(db)
    service.store_bars(
        manual.id, [Bar(date(2024, 1, 2), D(1)), Bar(date(2024, 2, 1), D(2))], "manual"
    )
    assert service.detect_gaps(listing_ref(manual)) == []
    _, empty = make_listing(db, ticker="NEW", isin="IE0000000009")
    assert service.detect_gaps(listing_ref(empty)) == []


@pytest.mark.parametrize(
    ("today", "stale"),
    [
        (date(2024, 1, 5), False),  # 3, 4 and 5 January: three trading days behind
        (date(2024, 1, 8), True),  # a fourth trading day (Monday) passes
        (date(2024, 1, 6), False),  # a weekend adds no trading days
    ],
)
def test_a_close_older_than_three_trading_days_is_stale(db, today: date, stale: bool) -> None:  # type: ignore[no-untyped-def]
    _, listing = make_listing(db)
    service = PriceService(db)
    service.store_bars(listing.id, [Bar(date(2024, 1, 2), D(100))], "primary")
    assert service.is_stale(listing_ref(listing), today) is stale


def test_no_close_at_all_is_stale_but_hand_priced_listings_never_are(db) -> None:  # type: ignore[no-untyped-def]
    _, listing = make_listing(db)
    service = PriceService(db)
    assert service.is_stale(listing_ref(listing), date(2024, 1, 5)) is True
    _, manual = make_listing(db, ticker="PRIV", mic="MANUAL", manual=True, isin=None, symbols={})
    service.store_bars(manual.id, [Bar(date(2020, 1, 2), D(1))], "manual")
    assert service.is_stale(listing_ref(manual), date(2024, 1, 5)) is False


def test_a_hand_priced_instrument_values_from_its_entered_price(db) -> None:  # type: ignore[no-untyped-def]
    _, listing = make_listing(db, ticker="PRIV", mic="MANUAL", manual=True, isin=None, symbols={})
    service = PriceService(db)
    service.set_manual_price(listing.id, date(2024, 3, 1), D("50"))
    service.set_manual_price(listing.id, date(2024, 4, 1), D("55"))
    db.commit()
    last = service.last_bar(listing.id, date(2024, 3, 20))
    assert last is not None and (last.date, last.close) == (date(2024, 3, 1), D("50"))
    latest = service.last_bar(listing.id)
    assert latest is not None and latest.close == D("55")
