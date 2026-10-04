"""Portfolio valuation on any day, and the nightly snapshots (FR-PF-01, FR-PF-10).

`Valuation` loads the ledger, the closes and the ECB rates once and can then value the portfolio
on as many days as needed. The same code answers "what is the summary for this period" (two or
three days) and writes the daily snapshots (thousands of days), so the two never disagree.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.analytics.valuation import (
    DayPoint,
    HoldingValue,
    PricePoint,
    make_day_point,
    value_holding,
)
from folio.db.models import Account
from folio.db.models_ledger import FxRate, LedgerTransaction, Listing, PortfolioSnapshot, PriceBar
from folio.domain import CostBasisMethod, LedgerState, TxIn, rebuild
from folio.ledger_service import account_transactions, to_txin
from folio.marketdata.fx import to_eur_multiplier

ZERO = Decimal(0)


@dataclass
class _Series:
    dates: list[date]
    values: list[Decimal]

    def at(self, day: date) -> tuple[date, Decimal] | None:
        index = bisect_right(self.dates, day)
        return None if index == 0 else (self.dates[index - 1], self.values[index - 1])


class Valuation:
    def __init__(
        self,
        accounts: dict[int, tuple[CostBasisMethod, list[TxIn]]],
        listing_currency: dict[int, str],
        bars: dict[int, _Series],
        rates: dict[str, _Series],
        instrument_listing: dict[int, int],
    ) -> None:
        self._accounts = accounts
        self._currency = listing_currency
        self._bars = bars
        self._rates = rates
        self._listing_of = instrument_listing
        self._dates = {a: sorted({t.trade_date for t in txs}) for a, (_, txs) in accounts.items()}
        self._states: dict[tuple[int, date], LedgerState] = {}
        self._multipliers: dict[tuple[str, date], Decimal | None] = {}

    @classmethod
    def load(cls, db: Session, *, account_id: int | None = None) -> Valuation:
        query = select(Account).where(Account.deleted_at.is_(None))
        if account_id is not None:
            query = query.where(Account.id == account_id)
        accounts: dict[int, tuple[CostBasisMethod, list[TxIn]]] = {}
        instrument_ids: set[int] = set()
        for account in db.scalars(query):
            txs = account_transactions(db, account.id)
            accounts[account.id] = (
                CostBasisMethod(account.cost_basis_method),
                [to_txin(t) for t in txs],
            )
            instrument_ids.update(t.instrument_id for t in txs if t.instrument_id is not None)

        listing_currency: dict[int, str] = {}
        instrument_listing: dict[int, int] = {}
        if instrument_ids:
            rows = db.scalars(
                select(Listing)
                .where(Listing.instrument_id.in_(instrument_ids))
                .order_by(Listing.pricing_primary.desc(), Listing.id)
            )
            for listing in rows:
                if listing.instrument_id not in instrument_listing:  # the primary listing
                    instrument_listing[listing.instrument_id] = listing.id
                    listing_currency[listing.id] = listing.currency

        bars: dict[int, _Series] = {}
        for listing_id in instrument_listing.values():
            found = db.execute(
                select(PriceBar.date, PriceBar.close)
                .where(PriceBar.listing_id == listing_id)
                .order_by(PriceBar.date)
            ).all()
            bars[listing_id] = _Series([r.date for r in found], [r.close for r in found])

        rates: dict[str, _Series] = {}
        for currency in {c for c in listing_currency.values() if c != "EUR"}:
            found_rates = db.execute(
                select(FxRate.date, FxRate.rate_per_eur)
                .where(FxRate.currency == currency)
                .order_by(FxRate.date)
            ).all()
            rates[currency] = _Series(
                [r.date for r in found_rates], [r.rate_per_eur for r in found_rates]
            )
        return cls(accounts, listing_currency, bars, rates, instrument_listing)

    # --- queries ----------------------------------------------------------------------------

    def first_date(self) -> date | None:
        firsts = [dates[0] for dates in self._dates.values() if dates]
        return min(firsts) if firsts else None

    def _state(self, account_id: int, day: date) -> LedgerState | None:
        dates = self._dates[account_id]
        index = bisect_right(dates, day)
        if index == 0:
            return None  # nothing had happened yet
        key = (account_id, dates[index - 1])
        state = self._states.get(key)
        if state is None:
            method, txs = self._accounts[account_id]
            state = rebuild((t for t in txs if t.trade_date <= key[1]), method)
            self._states[key] = state
        return state

    def _multiplier(self, currency: str, on: date) -> Decimal | None:
        if currency == "EUR":
            return Decimal(1)
        key = (currency, on)
        if key not in self._multipliers:
            series = self._rates.get(currency)
            found = None if series is None else series.at(on)
            self._multipliers[key] = None if found is None else to_eur_multiplier(found[1])
        return self._multipliers[key]

    def _price(self, instrument_id: int, day: date) -> PricePoint | None:
        listing_id = self._listing_of.get(instrument_id)
        series = self._bars.get(listing_id) if listing_id is not None else None
        found = None if series is None else series.at(day)
        if found is None or listing_id is None:
            return None
        multiplier = self._multiplier(self._currency[listing_id], found[0])
        return None if multiplier is None else PricePoint(found[0], found[1], multiplier)

    def point(self, day: date) -> DayPoint:
        """The portfolio as it stood at the end of `day`, valued at the latest closes."""
        holdings: list[HoldingValue] = []
        contributions, income, costs = ZERO, ZERO, ZERO
        for account_id in sorted(self._accounts):
            state = self._state(account_id, day)
            if state is None:
                continue
            contributions += state.net_contributions_eur
            income += state.total_income_eur
            costs += state.standalone_fees_eur + state.taxes_eur
            for instrument_id, position in sorted(state.positions.items()):
                if position.quantity == 0:
                    continue
                holdings.append(
                    value_holding(
                        account_id,
                        instrument_id,
                        position.quantity,
                        position.cost_basis_eur,
                        self._price(instrument_id, day),
                    )
                )
        return make_day_point(day, holdings, contributions, income, costs)


# --- snapshots ----------------------------------------------------------------------------------


def _holdings_json(point: DayPoint) -> list[dict[str, str | None]]:
    return [
        {
            "account_id": str(h.account_id),
            "instrument_id": str(h.instrument_id),
            "quantity": str(h.quantity),
            "cost_basis_eur": str(h.cost_basis_eur),
            "price": None if h.price is None else str(h.price.price),
            "price_date": None if h.price is None else h.price.date.isoformat(),
            "value_eur": None if h.value_eur is None else str(h.value_eur),
        }
        for h in point.holdings
    ]


def save_snapshots(
    db: Session,
    valuation: Valuation,
    start: date,
    end: date,
    today: date,
    *,
    include_locked: bool = False,
) -> int:
    """Write one snapshot per calendar day from `start` to `end` (idempotent: a re-run writes
    identical rows). Days before the first transaction are skipped. A locked 1 January snapshot
    is left as filed unless `include_locked` is set. Returns the number of days written."""
    first = valuation.first_date()
    if first is None:
        return 0
    day = max(start, first)
    existing = {
        row.date: row
        for row in db.scalars(
            select(PortfolioSnapshot).where(
                PortfolioSnapshot.date >= day, PortfolioSnapshot.date <= end
            )
        )
    }
    written = 0
    while day <= end:
        row = existing.get(day)
        if row is not None and row.locked and not include_locked:
            day += timedelta(days=1)
            continue
        point = valuation.point(day)
        peildatum = day.month == 1 and day.day == 1
        fields = {
            "total_value_eur": point.value_eur,
            "net_contributions_eur": point.net_contributions_eur,
            "cash_eur": ZERO,
            "income_eur": point.income_eur,
            "costs_eur": point.costs_eur,
            "unvalued_positions": point.unvalued,
            "positions": _holdings_json(point),
            "is_peildatum": peildatum,
            "locked": peildatum and today.year > day.year,  # the year has closed
        }
        if row is None:
            db.add(PortfolioSnapshot(date=day, **fields))
        else:
            for key, value in fields.items():
                setattr(row, key, value)
        written += 1
        day += timedelta(days=1)
    db.flush()
    return written


def lock_closed_years(db: Session, today: date) -> int:
    """Lock every 1 January snapshot whose year has closed (the Dutch Box 3 reference date)."""
    rows = db.scalars(
        select(PortfolioSnapshot).where(
            PortfolioSnapshot.is_peildatum.is_(True), PortfolioSnapshot.locked.is_(False)
        )
    )
    locked = 0
    for row in rows:
        if today.year > row.date.year:
            row.locked = True
            locked += 1
    db.flush()
    return locked


def first_transaction_date(db: Session) -> date | None:
    return db.scalar(
        select(LedgerTransaction.trade_date)
        .where(LedgerTransaction.deleted_at.is_(None), LedgerTransaction.status == "posted")
        .order_by(LedgerTransaction.trade_date)
        .limit(1)
    )
