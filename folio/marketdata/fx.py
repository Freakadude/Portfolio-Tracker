"""EUR conversion from ECB reference rates (FR-MD-06).

The ECB publishes `rate_per_eur` (units of a currency per 1 EUR) on TARGET working days. A
valuation on any other day uses the last earlier published rate. `fx_rate_to_eur`, the
multiplier stored on transactions and used by the ledger, is 1 / rate_per_eur rounded to ten
decimal places.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from sqlalchemy import func, select, union
from sqlalchemy.orm import Session

from folio.db.models_ledger import FxRate, LedgerTransaction, Listing
from folio.marketdata.ecb import EcbRates, FxObservation

_MULTIPLIER_QUANTUM = Decimal("1E-10")
_OVERLAP = timedelta(days=7)  # re-fetched on every catch-up so late revisions are picked up


class FxUnavailable(Exception):
    """No rate can be found; the message tells the owner what to do."""


@dataclass(frozen=True)
class RateOnDate:
    rate_per_eur: Decimal
    as_of: date  # the publication date actually used (earlier than asked on non-publication days)


def to_eur_multiplier(rate_per_eur: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 40
        return (Decimal(1) / rate_per_eur).quantize(_MULTIPLIER_QUANTUM, ROUND_HALF_EVEN)


class FxService:
    def __init__(self, db: Session, ecb: EcbRates | None = None) -> None:
        self._db = db
        self._ecb = ecb

    def rate_per_eur(self, currency: str, on: date) -> RateOnDate:
        currency = currency.upper()
        if currency == "EUR":
            return RateOnDate(Decimal(1), on)
        row = self._db.execute(
            select(FxRate.date, FxRate.rate_per_eur)
            .where(FxRate.currency == currency, FxRate.date <= on)
            .order_by(FxRate.date.desc())
            .limit(1)
        ).first()
        if row is None:
            raise FxUnavailable(
                f"No ECB rate for {currency} on or before {on.isoformat()}. "
                "Run the FX refresh (System > Refresh prices now) and try again."
            )
        return RateOnDate(row.rate_per_eur, row.date)

    def multiplier(self, currency: str, on: date) -> Decimal:
        """What to multiply an amount in `currency` by to get EUR on that day."""
        return to_eur_multiplier(self.rate_per_eur(currency, on).rate_per_eur)

    def latest_date(self, currency: str) -> date | None:
        return self._db.scalar(select(func.max(FxRate.date)).where(FxRate.currency == currency))

    def _fetch(
        self, currencies: Iterable[str], start: date, end: date | None
    ) -> list[FxObservation]:
        if self._ecb is None:
            raise RuntimeError("FxService needs an ECB client to refresh rates")
        wanted = sorted({c.upper() for c in currencies} - {"EUR"})
        if not wanted:
            return []
        # Only keep what was asked for, whatever the response contains.
        return [
            o
            for o in self._ecb.fetch(wanted, start, end)
            if o.currency in wanted and o.date >= start and (end is None or o.date <= end)
        ]

    def _store(self, observations: list[FxObservation], start: date) -> int:
        currencies = {o.currency for o in observations}
        existing = {
            (row.currency, row.date): row
            for row in self._db.scalars(
                select(FxRate).where(FxRate.currency.in_(currencies), FxRate.date >= start)
            )
        }
        changed = 0
        for obs in observations:
            row = existing.get((obs.currency, obs.date))
            if row is None:
                self._db.add(
                    FxRate(date=obs.date, currency=obs.currency, rate_per_eur=obs.rate_per_eur)
                )
                changed += 1
            elif row.rate_per_eur != obs.rate_per_eur:
                row.rate_per_eur = obs.rate_per_eur
                changed += 1
        self._db.flush()
        return changed

    def refresh(self, currencies: Iterable[str], start: date, end: date | None = None) -> int:
        """Fetch and store rates; safe to repeat. Returns the number of rows added or changed."""
        return self._store(self._fetch(currencies, start, end), start)

    def catch_up(self, currencies: Iterable[str], today: date, floor: date) -> int:
        """Fetch what is missing: from a week before the newest stored rate, or from `floor`
        (the earliest date any transaction needs) for a currency that has none yet.

        All calls to the ECB happen first and the rows are written afterwards: each call is
        charged to the usage counter through its own connection, which must not have to wait
        for an open write transaction on this session."""
        fetched: list[tuple[date, list[FxObservation]]] = []
        for currency in sorted({c.upper() for c in currencies} - {"EUR"}):
            latest = self.latest_date(currency)
            start = floor if latest is None else max(floor, latest - _OVERLAP)
            fetched.append((start, self._fetch([currency], start, today)))
        return sum(self._store(observations, start) for start, observations in fetched)


def needed_currencies(db: Session) -> set[str]:
    """Every non-EUR currency the ledger or a listing uses."""
    query = union(
        select(Listing.currency),
        select(LedgerTransaction.currency),
        select(LedgerTransaction.fees_currency),
        select(LedgerTransaction.taxes_currency),
    )
    return {c.upper() for (c,) in db.execute(query) if c} - {"EUR"}
