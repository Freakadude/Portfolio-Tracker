"""A fictional demo portfolio for working on the UI (`folio seed --demo`).

Everything here is invented: six hand-priced instruments (plus one that is only watched) with a
deterministic random-walk price history, a USD holding with made-up exchange rates, two years of
small monthly purchases, a sale and some dividends, three sleeves with targets, a benchmark and a
watchlist. It never contacts a provider and uses no real prices, ISINs or amounts.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from folio.db.models import Account
from folio.db.models_analytics import Sleeve, Watchlist, WatchlistItem
from folio.db.models_ledger import FxRate, Instrument, LedgerTransaction, Listing, PriceBar
from folio.ledger_service import TransactionIn, insert_transaction, normalize, rebuild_account
from folio.portfolio import Valuation, save_snapshots

CENT = Decimal("0.01")
SEED = 20241004


class DemoError(Exception):
    """The demo data cannot be added; the message is for the owner."""


@dataclass(frozen=True)
class DemoInstrument:
    name: str
    asset_class: str
    currency: str
    start_price: str
    drift: float  # average daily return
    volatility: float
    region: str
    sector: str
    sleeve: str | None  # None: watched but not held


INSTRUMENTS = (
    DemoInstrument(
        "Demo World Equity ETF",
        "ETF",
        "EUR",
        "80",
        0.00035,
        0.010,
        "Global",
        "Broad market",
        "Core",
    ),  # fmt: skip
    DemoInstrument(
        "Demo Europe Equity ETF",
        "ETF",
        "EUR",
        "45",
        0.00025,
        0.011,
        "Europe",
        "Broad market",
        "Core",
    ),  # fmt: skip
    DemoInstrument(
        "Demo Emerging Markets ETF",
        "ETF",
        "EUR",
        "30",
        0.00020,
        0.013,
        "Emerging markets",
        "Broad market",
        "Growth",
    ),  # fmt: skip
    DemoInstrument(
        "Demo Gold ETC", "ETC", "EUR", "55", 0.00030, 0.009, "Global", "Commodities", "Defensive"
    ),  # fmt: skip
    DemoInstrument(
        "Demo US Tech Stock",
        "EQUITY",
        "USD",
        "120",
        0.00050,
        0.018,
        "North America",
        "Technology",
        "Growth",
    ),  # fmt: skip
    DemoInstrument(
        "Demo Corporate Bond Fund",
        "FUND",
        "EUR",
        "100",
        0.00008,
        0.003,
        "Europe",
        "Bonds",
        "Defensive",
    ),  # fmt: skip
    # followed on the watchlist, never bought
    DemoInstrument(
        "Demo Dividend ETF", "ETF", "EUR", "25", 0.00022, 0.009, "Global", "Broad market", None
    ),  # fmt: skip
)

BENCHMARK = "Demo World Equity ETF"
# fictional targets, so the drift widgets have something to show
SLEEVES = (("Core", "60", "5"), ("Growth", "25", "5"), ("Defensive", "15", "5"))


def _is_empty(db: Session) -> bool:
    instruments = db.scalar(select(func.count()).select_from(Instrument)) or 0
    transactions = db.scalar(select(func.count()).select_from(LedgerTransaction)) or 0
    return instruments == 0 and transactions == 0


def _weekdays(start: date, end: date) -> list[date]:
    days, day = [], start
    while day <= end:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def _round(value: float) -> Decimal:
    return Decimal(str(value)).quantize(CENT, ROUND_HALF_EVEN)


def seed_demo(db: Session, today: date) -> dict[str, int]:
    """Add the demo portfolio. Refuses when instruments or transactions already exist."""
    if not _is_empty(db):
        raise DemoError(
            "Demo data can only be added to a database without instruments or transactions, so "
            "it never mixes with real holdings."
        )
    account = db.scalars(
        select(Account).where(Account.deleted_at.is_(None)).order_by(Account.id)
    ).first()
    if account is None:
        account = Account(name="Demo broker", broker="Demo")
        db.add(account)
        db.flush()

    start = date(today.year - 2, today.month, 1)
    days = _weekdays(start, today)
    rng = random.Random(SEED)  # noqa: S311 - fictional data, not cryptography

    sleeves: dict[str, Sleeve] = {}
    for order, (name, target, band) in enumerate(SLEEVES, start=1):
        sleeve = Sleeve(
            name=name, target_pct=Decimal(target), band_pct=Decimal(band), sort_order=order
        )
        db.add(sleeve)
        db.flush()
        sleeves[name] = sleeve

    listings: dict[str, Listing] = {}
    for spec in INSTRUMENTS:
        instrument = Instrument(
            isin=None,
            name=spec.name,
            asset_class=spec.asset_class,
            manual=True,
            tags=["demo"],
            distribution="DIST" if spec.asset_class == "FUND" else "ACC",
            region=spec.region,
            sector=spec.sector,
            sleeve_id=sleeves[spec.sleeve].id if spec.sleeve else None,
            is_benchmark=spec.name == BENCHMARK,
        )
        db.add(instrument)
        db.flush()
        listing = Listing(
            instrument_id=instrument.id,
            exchange_mic="MANUAL",
            ticker=spec.name.replace(" ", "").upper()[:30],
            currency=spec.currency,
            provider_symbols={},
            pricing_primary=True,
        )
        db.add(listing)
        db.flush()
        listings[spec.name] = listing
        price = float(spec.start_price)
        for day in days:
            price *= 1 + spec.drift + spec.volatility * rng.gauss(0, 1)
            price = max(price, 1.0)
            db.add(PriceBar(listing_id=listing.id, date=day, close=_round(price), source="demo"))

    rate = 1.08  # made-up USD per EUR
    for day in days:
        rate = min(1.25, max(0.95, rate + rng.gauss(0, 0.002)))
        db.add(
            FxRate(
                date=day, currency="USD", rate_per_eur=Decimal(str(round(rate, 4))), source="demo"
            )
        )
    db.flush()

    months: dict[tuple[int, int], date] = {}  # the first weekday of each month
    for d in days:
        months.setdefault((d.year, d.month), d)
    plan = {"Demo World Equity ETF": 300, "Demo Europe Equity ETF": 100,
            "Demo Emerging Markets ETF": 60, "Demo Gold ETC": 40}  # fmt: skip

    def close_on(name: str, day: date) -> Decimal:
        bar = db.scalar(
            select(PriceBar.close)
            .where(PriceBar.listing_id == listings[name].id, PriceBar.date <= day)
            .order_by(PriceBar.date.desc())
            .limit(1)
        )
        return bar if bar is not None else Decimal(1)

    created = 0

    def add(**body: object) -> None:
        nonlocal created
        fields = normalize(
            db, TransactionIn.model_validate({"account_id": account.id, **body}), today
        )
        insert_transaction(db, fields, source="demo")
        created += 1

    for day in months.values():
        for name, euros in plan.items():
            close = close_on(name, day)
            units = int(Decimal(euros) // close)
            if units >= 1:
                add(type="buy", trade_date=day, instrument_id=listings[name].instrument_id,
                    quantity=units, price=close, fees="1")  # fmt: skip
    tech = listings["Demo US Tech Stock"]
    tech_day = days[len(days) // 3]
    add(type="buy", trade_date=tech_day, instrument_id=tech.instrument_id, quantity=8,
        price=close_on("Demo US Tech Stock", tech_day), fees="1")  # fmt: skip
    sale_day = days[(2 * len(days)) // 3]
    add(type="sell", trade_date=sale_day, instrument_id=tech.instrument_id, quantity=3,
        price=close_on("Demo US Tech Stock", sale_day), fees="1")  # fmt: skip
    bond = listings["Demo Corporate Bond Fund"]
    bond_day = days[len(days) // 5]
    add(type="buy", trade_date=bond_day, instrument_id=bond.instrument_id, quantity=10,
        price=close_on("Demo Corporate Bond Fund", bond_day), fees="1")  # fmt: skip
    for fraction in (0.45, 0.75):
        paid = days[int(len(days) * fraction)]
        add(type="dividend", trade_date=paid, instrument_id=bond.instrument_id,
            net_amount_eur="12.40")  # fmt: skip

    watched = next(spec for spec in INSTRUMENTS if spec.sleeve is None)
    watchlist = Watchlist(name="Watchlist")
    db.add(watchlist)
    db.flush()
    db.add(
        WatchlistItem(
            watchlist_id=watchlist.id,
            instrument_id=listings[watched.name].instrument_id,
            note="Higher yield than the world ETF; wait for a pullback.",
        )
    )

    db.flush()
    rebuild_account(db, account)
    valuation = Valuation.load(db)
    snapshots = save_snapshots(db, valuation, start, today, today)
    return {"instruments": len(INSTRUMENTS), "transactions": created, "snapshots": snapshots}
