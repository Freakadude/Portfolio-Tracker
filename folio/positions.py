"""Positions with market values, joined at read time (FR-TX-05).

Cost basis, realized P&L and income come from the derived tables (or, for a past date, from
replaying the ledger up to it). Prices are the latest stored close on or before the valuation
date, converted with the ECB rate for that close's date. A position without a price is still
listed, with its market figures left empty rather than guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.db.models import Account
from folio.db.models_ledger import Instrument, Listing, Lot, Position, PriceBar
from folio.domain import Lot as DomainLot
from folio.domain import PositionMetrics, PositionState, Quote, position_metrics
from folio.domain.ledger import ZERO, precise
from folio.ledger_service import compute_state
from folio.marketdata.fx import FxService, FxUnavailable, to_eur_multiplier
from folio.marketdata.prices import PriceService, listing_ref


@dataclass(frozen=True)
class PriceInfo:
    date: date
    close: Decimal
    source: str
    overridden: bool
    stale: bool
    previous_close: Decimal | None


@dataclass
class PositionRow:
    account: Account
    instrument: Instrument
    listing: Listing | None
    state: PositionState
    price: PriceInfo | None = None
    metrics: PositionMetrics | None = None
    weight: Decimal | None = None
    note: str | None = None


@dataclass
class Totals:
    market_value_eur: Decimal = ZERO
    cost_basis_eur: Decimal = ZERO
    unrealized_pnl_eur: Decimal = ZERO
    realized_pnl_eur: Decimal = ZERO
    income_eur: Decimal = ZERO
    day_change_eur: Decimal | None = ZERO
    unvalued: int = 0
    unrealized_pct: Decimal | None = None
    positions: int = 0
    extra: dict[str, str] = field(default_factory=dict)


def _states_from_tables(db: Session, account: Account) -> dict[int, PositionState]:
    """The persisted derived tables as domain objects."""
    states: dict[int, PositionState] = {}
    for row in db.scalars(select(Position).where(Position.account_id == account.id)):
        states[row.instrument_id] = PositionState(
            instrument_id=row.instrument_id,
            realized_pnl_eur=row.realized_pnl_eur,
            income_eur=row.income_eur,
            invested_eur=row.invested_eur,
            proceeds_eur=row.proceeds_eur,
            first_trade_date=row.first_trade_date,
        )
    for lot in db.scalars(select(Lot).where(Lot.account_id == account.id).order_by(Lot.id)):
        states[lot.instrument_id].lots.append(
            DomainLot(
                lot.buy_transaction_id,
                lot.instrument_id,
                lot.trade_date,
                lot.open_quantity,
                lot.cost_eur,
                lot.cost_native,
            )
        )
    return states


def account_states(db: Session, account: Account, as_of: date | None) -> dict[int, PositionState]:
    if as_of is None:
        return _states_from_tables(db, account)
    return dict(compute_state(db, account, as_of=as_of).positions)


def merge_states(instrument_id: int, states: list[PositionState]) -> PositionState:
    """One position across several accounts (for the instrument detail page)."""
    merged = PositionState(instrument_id=instrument_id)
    for state in states:
        merged.lots.extend(state.lots)
        merged.realized_pnl_eur += state.realized_pnl_eur
        merged.income_eur += state.income_eur
        merged.invested_eur += state.invested_eur
        merged.proceeds_eur += state.proceeds_eur
        if state.first_trade_date and (
            merged.first_trade_date is None or state.first_trade_date < merged.first_trade_date
        ):
            merged.first_trade_date = state.first_trade_date
    return merged


def primary_listing(db: Session, instrument_id: int) -> Listing | None:
    return db.scalars(
        select(Listing)
        .where(Listing.instrument_id == instrument_id)
        .order_by(Listing.pricing_primary.desc(), Listing.id)
        .limit(1)
    ).first()


def quote_for(
    db: Session, instrument: Instrument, listing: Listing | None, valuation: date, today: date
) -> tuple[Quote | None, PriceInfo | None, str | None]:
    """The latest close on or before `valuation`, with the ECB rate of its date."""
    if listing is None:
        return None, None, "This instrument has no listing to price."
    prices = PriceService(db)
    bar = prices.last_bar(listing.id, valuation)
    if bar is None:
        return None, None, "No price yet."
    previous = db.scalars(
        select(PriceBar)
        .where(PriceBar.listing_id == listing.id, PriceBar.date < bar.date)
        .order_by(PriceBar.date.desc())
        .limit(1)
    ).first()
    fx = FxService(db)
    try:
        rate = to_eur_multiplier(fx.rate_per_eur(listing.currency, bar.date).rate_per_eur)
        prev_rate = (
            to_eur_multiplier(fx.rate_per_eur(listing.currency, previous.date).rate_per_eur)
            if previous
            else None
        )
    except FxUnavailable as exc:
        return None, None, str(exc)
    info = PriceInfo(
        date=bar.date,
        close=bar.close,
        source=bar.source,
        overridden=bar.overridden,
        stale=prices.is_stale(listing_ref(listing, instrument.isin), today),
        previous_close=previous.close if previous else None,
    )
    quote = Quote(bar.close, rate, previous.close if previous else None, prev_rate)
    return quote, info, None


def load_positions(
    db: Session,
    *,
    account_id: int | None = None,
    as_of: date | None = None,
    include_closed: bool = False,
    today: date | None = None,
) -> tuple[list[PositionRow], Totals]:
    today = today or date.today()
    valuation = as_of or today
    accounts = list(
        db.scalars(select(Account).where(Account.deleted_at.is_(None)).order_by(Account.name))
    )
    rows: list[PositionRow] = []
    instruments: dict[int, Instrument] = {}
    listings: dict[int, Listing | None] = {}
    for account in accounts:
        for instrument_id, state in account_states(db, account, as_of).items():
            if state.quantity == 0 and not include_closed:
                continue
            instrument = instruments.get(instrument_id) or db.get(Instrument, instrument_id)
            if instrument is None:
                continue
            instruments[instrument_id] = instrument
            if instrument_id not in listings:
                listings[instrument_id] = primary_listing(db, instrument_id)
            rows.append(PositionRow(account, instrument, listings[instrument_id], state))

    quotes: dict[int, tuple[Quote | None, PriceInfo | None, str | None]] = {}
    for row in rows:
        iid = row.instrument.id
        if iid not in quotes:
            quotes[iid] = quote_for(db, row.instrument, row.listing, valuation, today)
        quote, info, note = quotes[iid]
        row.price, row.note = info, note
        if quote is not None:
            row.metrics = position_metrics(row.state, quote)

    with precise():
        portfolio_value = sum((r.metrics.market_value_eur for r in rows if r.metrics), ZERO)
        for row in rows:
            if row.metrics is not None and portfolio_value != 0:
                row.weight = row.metrics.market_value_eur / portfolio_value

    shown = [r for r in rows if account_id is None or r.account.id == account_id]
    return shown, totals_for(shown)


def totals_for(rows: list[PositionRow]) -> Totals:
    totals = Totals(positions=len(rows))
    with precise():
        for row in rows:
            totals.cost_basis_eur += row.state.cost_basis_eur
            totals.realized_pnl_eur += row.state.realized_pnl_eur
            totals.income_eur += row.state.income_eur
            if row.metrics is None:
                if row.state.quantity != 0:
                    totals.unvalued += 1
                    totals.day_change_eur = None
                continue
            totals.market_value_eur += row.metrics.market_value_eur
            totals.unrealized_pnl_eur += row.metrics.unrealized_pnl_eur
            if totals.day_change_eur is not None:
                if row.metrics.day_change_eur is None:
                    totals.day_change_eur = None
                else:
                    totals.day_change_eur += row.metrics.day_change_eur
        valued_cost = sum((r.state.cost_basis_eur for r in rows if r.metrics is not None), ZERO)
        totals.unrealized_pct = (
            None if valued_cost == 0 else totals.unrealized_pnl_eur / valued_cost
        )
    return totals
