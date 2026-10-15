"""How far a holding sits from its best price since it was first bought (ADR 0063).

* The peak price is the highest daily close of the instrument's primary listing from the day of
  the first buy (over all accounts), in the trading currency, like the Price column. A newer
  price that is above every close counts as the peak (then the fall-off is 0).
* The fall-off is the last known price against the peak, never above 0.
* The peak value is what today's holding would be worth at the peak price: today's value times
  peak over last price, at today's exchange rate. Its fall-off is today's value against it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from folio.db.models_ledger import LedgerTransaction, PriceBar

ZERO = Decimal(0)
ONE = Decimal(1)
RATIO_PLACES = Decimal("0.000001")


@dataclass(frozen=True)
class Peak:
    price: Decimal  # the highest known price, trading currency
    day: dt.date  # when it was reached
    last: Decimal  # the price it is compared with
    fall_off: Decimal  # last / peak - 1, 0 or below
    since: dt.date  # the first buy


def fall_off(last: Decimal, peak: Decimal) -> Decimal:
    """The change from the peak to `last` as a ratio (-0.12 is 12 % below the peak)."""
    if peak <= ZERO:
        return ZERO
    return min(ZERO, (last / peak - ONE).quantize(RATIO_PLACES))


def peak_value(market_value: Decimal | None, last: Decimal, peak: Decimal) -> Decimal | None:
    """What today's holding fetches at the peak price (today's quantity, today's rate)."""
    if market_value is None or last <= ZERO:
        return None
    return market_value * peak / last


def first_buy(db: Session, instrument_id: int) -> dt.date | None:
    return db.scalar(
        select(func.min(LedgerTransaction.trade_date)).where(
            LedgerTransaction.instrument_id == instrument_id,
            LedgerTransaction.type == "buy",
            LedgerTransaction.status == "posted",
            LedgerTransaction.deleted_at.is_(None),
        )
    )


def peak_of(
    db: Session,
    listing_id: int,
    instrument_id: int,
    last: Decimal,
    last_day: dt.date,
) -> Peak | None:
    """The peak of one instrument, or None when it has no buy or no price since the first buy."""
    since = first_buy(db, instrument_id)
    if since is None or last <= ZERO:
        return None
    top = db.execute(
        select(PriceBar.close, PriceBar.date)
        .where(PriceBar.listing_id == listing_id, PriceBar.date >= since)
        .order_by(PriceBar.close.desc(), PriceBar.date.desc())
        .limit(1)
    ).first()
    price, day = (last, last_day) if top is None else (top[0], top[1])
    if last > price:
        price, day = last, last_day
    return Peak(price, day, last, fall_off(last, price), since)


def peaks_for(db: Session, rows: Sequence[object]) -> dict[int, Peak]:
    """The peak of every position row that has a listing and a price, by instrument id. `rows`
    are `PositionRow`s (typed loosely to keep this module free of the positions import)."""
    out: dict[int, Peak] = {}
    for row in rows:
        listing = getattr(row, "listing", None)
        price = getattr(row, "price", None)
        instrument = getattr(row, "instrument", None)
        if listing is None or price is None or instrument is None or instrument.id in out:
            continue
        quoted = price.delayed_price is not None
        last = price.delayed_price if quoted else price.close
        day = price.delayed_at.date() if quoted and price.delayed_at else price.date
        found = peak_of(db, listing.id, instrument.id, last, day)
        if found is not None:
            out[instrument.id] = found
    return out
