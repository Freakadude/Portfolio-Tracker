"""Ledger, market-data and job tables (Phase 1).

Transactions are the only source of truth. Lot, lot_match and position are derived and rebuilt
whenever a transaction for that account and instrument changes.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from folio.db.base import Base, SoftDeleteMixin, utcnow
from folio.db.types import DecimalText, UTCDateTime

# --- Ledger ------------------------------------------------------------------------------------


class Instrument(Base, SoftDeleteMixin):
    __tablename__ = "instrument"

    isin: Mapped[str | None] = mapped_column(String(12), unique=True, default=None)
    name: Mapped[str] = mapped_column(String(200))
    asset_class: Mapped[str] = mapped_column(String(10))  # ETF ETC EQUITY BOND FUND CASH OTHER
    issuer: Mapped[str | None] = mapped_column(String(100), default=None)
    domicile: Mapped[str | None] = mapped_column(String(2), default=None)
    ter_pct: Mapped[Decimal | None] = mapped_column(DecimalText, default=None)
    distribution: Mapped[str | None] = mapped_column(String(4), default=None)  # ACC | DIST
    tags: Mapped[Any] = mapped_column(JSON, default=list)
    coupon_pct: Mapped[Decimal | None] = mapped_column(DecimalText, default=None)
    maturity_date: Mapped[date | None] = mapped_column(Date, default=None)
    rating: Mapped[str | None] = mapped_column(String(10), default=None)
    status: Mapped[str] = mapped_column(String(10), default="active")  # active | archived
    manual: Mapped[bool] = mapped_column(Boolean, default=False)  # priced by hand
    region: Mapped[str | None] = mapped_column(String(40), default=None)
    sector: Mapped[str | None] = mapped_column(String(60), default=None)
    sleeve_id: Mapped[int | None] = mapped_column(ForeignKey("sleeve.id"), default=None)
    is_benchmark: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")


class Listing(Base):
    __tablename__ = "listing"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id"), index=True)
    exchange_mic: Mapped[str] = mapped_column(String(10))
    ticker: Mapped[str] = mapped_column(String(30))
    currency: Mapped[str] = mapped_column(String(3))
    provider_symbols: Mapped[Any] = mapped_column(JSON, default=dict)
    pricing_primary: Mapped[bool] = mapped_column(Boolean, default=False)


class ImportPreset(Base):
    __tablename__ = "import_preset"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    config: Mapped[Any] = mapped_column(JSON)  # mapping, date format, separators, buy/sell rule


class ImportBatch(Base):
    __tablename__ = "import_batch"

    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    file_name: Mapped[str] = mapped_column(String(255))
    preset_id: Mapped[int | None] = mapped_column(ForeignKey("import_preset.id"), default=None)
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_imported: Mapped[int] = mapped_column(Integer, default=0)
    rows_skipped: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(12), default="preview")  # preview committed undone
    error_report: Mapped[Any] = mapped_column(JSON, default=list)
    config: Mapped[Any] = mapped_column(JSON, default=dict)
    committed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


class LedgerTransaction(Base, SoftDeleteMixin):
    __tablename__ = "ledger_transaction"
    __table_args__ = (
        Index("ix_ledger_tx_account_instrument", "account_id", "instrument_id", "trade_date"),
        # Makes imports idempotent; a soft-deleted (undone) row no longer blocks a re-import.
        Index(
            "uq_ledger_tx_external_ref",
            "account_id",
            "external_ref",
            unique=True,
            sqlite_where=text("external_ref IS NOT NULL AND deleted_at IS NULL"),
        ),
    )

    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instrument.id"), default=None)
    type: Mapped[str] = mapped_column(String(15))
    status: Mapped[str] = mapped_column(String(8), default="posted")  # posted | draft
    trade_date: Mapped[date] = mapped_column(Date)
    settle_date: Mapped[date | None] = mapped_column(Date, default=None)
    quantity: Mapped[Decimal] = mapped_column(DecimalText, default=Decimal(0))
    price: Mapped[Decimal] = mapped_column(DecimalText, default=Decimal(0))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    fx_rate_to_eur: Mapped[Decimal] = mapped_column(DecimalText, default=Decimal(1))
    fees: Mapped[Decimal] = mapped_column(DecimalText, default=Decimal(0))
    fees_currency: Mapped[str] = mapped_column(String(3), default="EUR")
    fees_fx_rate_to_eur: Mapped[Decimal] = mapped_column(DecimalText, default=Decimal(1))
    taxes: Mapped[Decimal] = mapped_column(DecimalText, default=Decimal(0))
    taxes_currency: Mapped[str] = mapped_column(String(3), default="EUR")
    taxes_fx_rate_to_eur: Mapped[Decimal] = mapped_column(DecimalText, default=Decimal(1))
    net_amount_eur: Mapped[Decimal | None] = mapped_column(DecimalText, default=None)
    ratio: Mapped[Decimal | None] = mapped_column(DecimalText, default=None)  # splits
    note: Mapped[str | None] = mapped_column(Text, default=None)
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual import seed ...
    import_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_batch.id"), default=None, index=True
    )
    external_ref: Mapped[str | None] = mapped_column(String(100), default=None)


class Lot(Base):
    """Derived: the open part of one buy (or the pooled holding under average cost)."""

    __tablename__ = "lot"
    __table_args__ = (Index("ix_lot_account_instrument", "account_id", "instrument_id"),)

    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id"))
    buy_transaction_id: Mapped[int] = mapped_column(ForeignKey("ledger_transaction.id"))
    trade_date: Mapped[date] = mapped_column(Date)
    open_quantity: Mapped[Decimal] = mapped_column(DecimalText)
    cost_eur: Mapped[Decimal] = mapped_column(DecimalText)
    cost_native: Mapped[Decimal] = mapped_column(DecimalText)


class LotMatch(Base):
    """Derived: explains every realized P&L number, one row per lot slice of a sell."""

    __tablename__ = "lot_match"

    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id"))
    sell_transaction_id: Mapped[int] = mapped_column(
        ForeignKey("ledger_transaction.id"), index=True
    )
    lot_buy_transaction_id: Mapped[int] = mapped_column(ForeignKey("ledger_transaction.id"))
    quantity: Mapped[Decimal] = mapped_column(DecimalText)
    cost_eur: Mapped[Decimal] = mapped_column(DecimalText)
    proceeds_eur: Mapped[Decimal] = mapped_column(DecimalText)
    realized_pnl_eur: Mapped[Decimal] = mapped_column(DecimalText)


class Position(Base):
    """Derived: current holding of one instrument in one account."""

    __tablename__ = "position"
    __table_args__ = (UniqueConstraint("account_id", "instrument_id"),)

    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id"))
    quantity: Mapped[Decimal] = mapped_column(DecimalText)
    cost_basis_eur: Mapped[Decimal] = mapped_column(DecimalText)
    cost_basis_native: Mapped[Decimal] = mapped_column(DecimalText)
    avg_cost_eur: Mapped[Decimal | None] = mapped_column(DecimalText, default=None)
    realized_pnl_eur: Mapped[Decimal] = mapped_column(DecimalText)
    income_eur: Mapped[Decimal] = mapped_column(DecimalText)
    invested_eur: Mapped[Decimal] = mapped_column(DecimalText)
    proceeds_eur: Mapped[Decimal] = mapped_column(DecimalText)
    first_trade_date: Mapped[date | None] = mapped_column(Date, default=None)


class CorporateAction(Base):
    __tablename__ = "corporate_action"
    __table_args__ = (UniqueConstraint("instrument_id", "type", "ex_date"),)

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id"))
    type: Mapped[str] = mapped_column(String(20))  # split | isin_change | ...
    ex_date: Mapped[date] = mapped_column(Date)
    ratio: Mapped[Decimal | None] = mapped_column(DecimalText, default=None)
    new_isin: Mapped[str | None] = mapped_column(String(12), default=None)
    status: Mapped[str] = mapped_column(
        String(10), default="proposed"
    )  # proposed applied dismissed
    applied_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    source: Mapped[str | None] = mapped_column(String(30), default=None)


# --- Market data -------------------------------------------------------------------------------


class PriceBar(Base):
    __tablename__ = "price_bar"
    __table_args__ = (UniqueConstraint("listing_id", "date"),)

    listing_id: Mapped[int] = mapped_column(ForeignKey("listing.id"))
    date: Mapped[date] = mapped_column(Date)  # exchange-local trading date
    open: Mapped[Decimal | None] = mapped_column(DecimalText, default=None)
    high: Mapped[Decimal | None] = mapped_column(DecimalText, default=None)
    low: Mapped[Decimal | None] = mapped_column(DecimalText, default=None)
    close: Mapped[Decimal] = mapped_column(DecimalText)
    adj_close: Mapped[Decimal | None] = mapped_column(DecimalText, default=None)
    volume: Mapped[Decimal | None] = mapped_column(DecimalText, default=None)
    source: Mapped[str] = mapped_column(String(20))  # provider name or "manual"
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    overridden: Mapped[bool] = mapped_column(Boolean, default=False)


class FxRate(Base):
    __tablename__ = "fx_rate"
    __table_args__ = (UniqueConstraint("date", "currency"),)

    date: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    rate_per_eur: Mapped[Decimal] = mapped_column(DecimalText)  # units of currency per 1 EUR
    source: Mapped[str] = mapped_column(String(20), default="ecb")


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshot"

    date: Mapped[date] = mapped_column(Date, unique=True)
    total_value_eur: Mapped[Decimal] = mapped_column(DecimalText)
    net_contributions_eur: Mapped[Decimal] = mapped_column(DecimalText)
    cash_eur: Mapped[Decimal] = mapped_column(DecimalText, default=Decimal(0))
    income_eur: Mapped[Decimal] = mapped_column(
        DecimalText, default=Decimal(0), server_default="0"
    )  # cumulative dividends and interest
    costs_eur: Mapped[Decimal] = mapped_column(
        DecimalText, default=Decimal(0), server_default="0"
    )  # cumulative standalone fees and taxes
    unvalued_positions: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    positions: Mapped[Any] = mapped_column(JSON, default=list)
    is_peildatum: Mapped[bool] = mapped_column(Boolean, default=False)  # 1 January
    locked: Mapped[bool] = mapped_column(Boolean, default=False)  # peildatum once the year closes


class ProviderCall(Base):
    """Calls made to a provider per UTC day (FR-MD-10); the scheduler never exceeds the budget."""

    __tablename__ = "provider_call"
    __table_args__ = (UniqueConstraint("provider", "day"),)

    provider: Mapped[str] = mapped_column(String(30))
    day: Mapped[date] = mapped_column(Date)
    count: Mapped[int] = mapped_column(Integer, default=0)


# --- Jobs --------------------------------------------------------------------------------------


class JobRequest(Base):
    """User actions that need the worker; the worker polls this table every 5 seconds."""

    __tablename__ = "job_request"

    job: Mapped[str] = mapped_column(String(50))
    params: Mapped[Any] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(10), default="pending", index=True)
    picked_up_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)


class JobRun(Base):
    __tablename__ = "job_run"

    job: Mapped[str] = mapped_column(String(50), index=True)
    params: Mapped[Any] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    status: Mapped[str] = mapped_column(String(10), default="running")  # running ok failed
    log: Mapped[str | None] = mapped_column(Text, default=None)
