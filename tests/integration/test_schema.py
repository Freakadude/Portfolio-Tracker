from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from folio.config import Settings
from folio.db import models  # noqa: F401  (registers every table on Base.metadata)
from folio.db.base import Base, utcnow
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import Account
from folio.db.models_ledger import (
    FxRate,
    Instrument,
    LedgerTransaction,
    Listing,
    PriceBar,
    ProviderCall,
)


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


def _account(db: Session) -> Account:
    account = Account(name="Test")
    db.add(account)
    db.flush()
    return account


def _tx(account: Account, **kwargs: object) -> LedgerTransaction:
    defaults: dict[str, object] = {
        "account_id": account.id,
        "type": "deposit",
        "trade_date": date(2024, 1, 2),
    }
    return LedgerTransaction(**{**defaults, **kwargs})


def test_models_and_migrations_agree(settings: Settings) -> None:
    """If a model changes without a migration, this fails (and the other way round)."""
    engine = make_engine(settings.db_url)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        assert compare_metadata(ctx, Base.metadata) == []


def test_all_spec_tables_exist(settings: Settings) -> None:
    from sqlalchemy import inspect

    tables = set(inspect(make_engine(settings.db_url)).get_table_names())
    expected = {
        "instrument", "listing", "ledger_transaction", "lot", "lot_match", "position",
        "corporate_action", "import_batch", "import_preset", "price_bar", "fx_rate",
        "portfolio_snapshot", "provider_call", "job_request", "job_run",
    }  # fmt: skip
    assert expected <= tables


def test_decimals_and_dates_round_trip_exactly(db: Session) -> None:
    account = _account(db)
    tx = _tx(
        account,
        type="buy",
        quantity=Decimal("12.345678"),
        price=Decimal("101.2345"),
        fx_rate_to_eur=Decimal("0.918273"),
        fees=Decimal("1.05"),
    )
    db.add(tx)
    db.commit()
    db.expire_all()
    got = db.scalars(select(LedgerTransaction)).one()
    assert (got.quantity, got.price, got.fx_rate_to_eur, got.fees) == (
        Decimal("12.345678"),
        Decimal("101.2345"),
        Decimal("0.918273"),
        Decimal("1.05"),
    )
    assert got.trade_date == date(2024, 1, 2)
    assert got.created_at.tzinfo is UTC and abs(got.created_at - utcnow()).seconds < 60


def test_external_ref_is_unique_per_account_but_not_after_undo(db: Session) -> None:
    account = _account(db)
    db.add(_tx(account, external_ref="abc"))
    db.commit()
    db.add(_tx(account, external_ref="abc"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    first = db.scalars(select(LedgerTransaction)).one()
    first.deleted_at = datetime.now(UTC)  # an undone import no longer blocks a re-import
    db.commit()
    db.add(_tx(account, external_ref="abc"))
    db.commit()

    other = Account(name="Other")
    db.add(other)
    db.flush()
    db.add(_tx(other, external_ref="abc"))  # same ref in another account is fine
    db.add(_tx(account, external_ref=None))
    db.add(_tx(account, external_ref=None))  # no ref: never a duplicate
    db.commit()


def test_one_price_bar_per_listing_and_day(db: Session) -> None:
    inst = Instrument(isin="IE00B5BMR087", name="S&P 500", asset_class="ETF")
    db.add(inst)
    db.flush()
    listing = Listing(instrument_id=inst.id, exchange_mic="XETR", ticker="SXR8", currency="EUR")
    db.add(listing)
    db.flush()
    db.add(PriceBar(listing_id=listing.id, date=date(2024, 1, 2), close=Decimal("500"), source="x"))
    db.commit()
    db.add(PriceBar(listing_id=listing.id, date=date(2024, 1, 2), close=Decimal("501"), source="y"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_isin_is_unique_and_cash_may_have_none(db: Session) -> None:
    db.add(Instrument(isin="IE00B5BMR087", name="A", asset_class="ETF"))
    db.add(Instrument(isin=None, name="Cash EUR", asset_class="CASH"))
    db.add(Instrument(isin=None, name="Cash USD", asset_class="CASH"))
    db.commit()
    db.add(Instrument(isin="IE00B5BMR087", name="B", asset_class="ETF"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_foreign_keys_are_enforced(db: Session) -> None:
    db.add(_tx(Account(id=999, name="ghost")))  # no such account row
    with pytest.raises(IntegrityError):
        db.commit()


def test_provider_call_and_fx_rate_are_unique(db: Session) -> None:
    db.add(ProviderCall(provider="eodhd", day=date(2024, 1, 2), count=1))
    db.add(FxRate(date=date(2024, 1, 2), currency="USD", rate_per_eur=Decimal("1.0950")))
    db.commit()
    db.add(ProviderCall(provider="eodhd", day=date(2024, 1, 2), count=1))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.add(FxRate(date=date(2024, 1, 2), currency="USD", rate_per_eur=Decimal("1.1")))
    with pytest.raises(IntegrityError):
        db.commit()
