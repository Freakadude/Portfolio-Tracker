from datetime import date
from decimal import Decimal

import httpx
import pytest

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import Account
from folio.db.models_ledger import FxRate, LedgerTransaction
from folio.marketdata.ecb import EcbRates
from folio.marketdata.fx import FxService, FxUnavailable, needed_currencies, to_eur_multiplier
from tests.marketdata_helpers import Scripted, client, make_listing, respond

D = Decimal


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


def ecb_with_recording() -> tuple[EcbRates, Scripted]:
    scripted = Scripted(lambda r: respond("ecb_exr.csv", content_type="text/csv"))
    return EcbRates(client("ecb", scripted)), scripted


def loaded(db) -> FxService:  # type: ignore[no-untyped-def]
    ecb, _ = ecb_with_recording()
    service = FxService(db, ecb)
    service.refresh(["USD", "GBP"], date(2024, 12, 20), date(2025, 1, 6))
    db.commit()
    return service


def test_refresh_stores_the_recorded_rates_and_is_idempotent(db) -> None:  # type: ignore[no-untyped-def]
    ecb, _ = ecb_with_recording()
    service = FxService(db, ecb)
    assert service.refresh(["USD", "GBP", "EUR"], date(2024, 12, 20), date(2025, 1, 6)) == 18
    db.commit()
    assert service.refresh(["USD", "GBP"], date(2024, 12, 20), date(2025, 1, 6)) == 0
    assert db.query(FxRate).count() == 18
    assert service.rate_per_eur("GBP", date(2024, 12, 24)).rate_per_eur == D("0.82805")


def test_a_saturday_uses_fridays_rate(db) -> None:  # type: ignore[no-untyped-def]
    service = loaded(db)
    saturday = service.rate_per_eur("USD", date(2024, 12, 21))
    friday = service.rate_per_eur("USD", date(2024, 12, 20))
    assert saturday == friday and saturday.as_of == date(2024, 12, 20)


def test_holidays_use_the_last_published_rate(db) -> None:  # type: ignore[no-untyped-def]
    service = loaded(db)
    assert service.rate_per_eur("GBP", date(2024, 12, 25)).as_of == date(2024, 12, 24)
    assert service.rate_per_eur("GBP", date(2024, 12, 26)).as_of == date(2024, 12, 24)
    assert service.rate_per_eur("GBP", date(2025, 1, 1)).as_of == date(2024, 12, 31)


def test_eur_needs_no_rate(db) -> None:  # type: ignore[no-untyped-def]
    service = FxService(db)
    assert service.rate_per_eur("EUR", date(2024, 1, 1)).rate_per_eur == D(1)
    assert service.multiplier("eur", date(2024, 1, 1)) == D(1)


def test_missing_rate_gives_a_plain_message(db) -> None:  # type: ignore[no-untyped-def]
    service = loaded(db)
    with pytest.raises(FxUnavailable, match=r"No ECB rate for USD on or before 2024-12-19"):
        service.rate_per_eur("USD", date(2024, 12, 19))
    with pytest.raises(FxUnavailable, match="Refresh prices now"):
        service.rate_per_eur("JPY", date(2025, 1, 2))


def test_multiplier_is_the_reciprocal_rounded_to_ten_places(db) -> None:  # type: ignore[no-untyped-def]
    service = loaded(db)
    multiplier = service.multiplier("GBP", date(2024, 12, 24))
    assert multiplier == to_eur_multiplier(D("0.82805")) == D("1.2076565425")
    assert abs(D(100) / D("0.82805") - D(100) * multiplier) < D("0.000001")


def test_catch_up_re_fetches_from_a_week_before_the_newest_rate(db) -> None:  # type: ignore[no-untyped-def]
    ecb, scripted = ecb_with_recording()
    service = FxService(db, ecb)
    service.refresh(["USD"], date(2024, 12, 20), date(2025, 1, 6))
    db.commit()
    service.catch_up(["USD", "EUR"], today=date(2025, 1, 10), floor=date(2020, 1, 1))
    last = scripted.requests[-1].url.params
    assert last["startPeriod"] == "2024-12-30" and last["endPeriod"] == "2025-01-10"
    # a currency with nothing stored starts from the floor (the earliest transaction)
    service.catch_up(["GBP"], today=date(2025, 1, 10), floor=date(2024, 6, 1))
    assert scripted.requests[-1].url.params["startPeriod"] == "2024-06-01"


def test_refresh_without_an_ecb_client_is_a_programming_error(db) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(RuntimeError):
        FxService(db).refresh(["USD"], date(2024, 1, 1))


def test_an_unreachable_ecb_is_reported(db) -> None:  # type: ignore[no-untyped-def]
    scripted = Scripted(lambda r: httpx.Response(504, text="down"))
    with pytest.raises(Exception, match="ecb did not answer"):
        FxService(db, EcbRates(client("ecb", scripted))).refresh(["USD"], date(2024, 12, 20))


def test_needed_currencies_cover_listings_and_transactions(db) -> None:  # type: ignore[no-untyped-def]
    make_listing(db, ticker="AAA", currency="USD", isin="IE0000000001")
    make_listing(db, ticker="BBB", currency="EUR", isin="IE0000000002")
    account = Account(name="A")
    db.add(account)
    db.flush()
    db.add(
        LedgerTransaction(
            account_id=account.id, type="buy", trade_date=date(2024, 1, 2),
            currency="CHF", fees_currency="GBP", taxes_currency="EUR",
        )
    )  # fmt: skip
    db.commit()
    assert needed_currencies(db) == {"USD", "CHF", "GBP"}
