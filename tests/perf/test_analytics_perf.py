"""NFR-03: dashboard data endpoints answer in under 300 ms (p95) for 10 years x 50 instruments.

The first request after a change builds the analytics context (one pass over the ledger and
the prices); that cost is measured and bounded separately, since a dashboard's many requests
are answered from the cached context.
"""

import statistics
import time
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from folio.analytics_service import clear_cache
from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import Account
from folio.db.models_ledger import Instrument, LedgerTransaction, Listing, PriceBar
from tests.conftest import PASSWORD, USERNAME

pytestmark = pytest.mark.slow

INSTRUMENTS = 50
YEARS = 10
AS_OF = date(2025, 12, 31)


def weekdays(start: date, end: date) -> list[date]:
    days, day = [], start
    while day <= end:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


@pytest.fixture
def seeded(settings: Settings, client: TestClient, owner: None) -> TestClient:
    client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    start = date(AS_OF.year - YEARS + 1, 1, 1)
    days = weekdays(start, AS_OF)
    with make_session_factory(make_engine(settings.db_url))() as db:
        account = Account(name="Perf")
        db.add(account)
        db.flush()
        for n in range(INSTRUMENTS):
            instrument = Instrument(
                isin=None,
                name=f"Fund {n}",
                asset_class="ETF",
                region="US" if n % 2 else "EU",
                sector=f"S{n % 7}",
            )
            db.add(instrument)
            db.flush()
            listing = Listing(
                instrument_id=instrument.id,
                exchange_mic="XETR",
                ticker=f"T{n}",
                currency="EUR",
                pricing_primary=True,
            )
            db.add(listing)
            db.flush()
            db.bulk_save_objects(
                [
                    PriceBar(
                        listing_id=listing.id,
                        date=d,
                        close=Decimal(100 + (i * (n + 3)) % 97) / Decimal(10) + Decimal(n),
                        source="perf",
                    )
                    for i, d in enumerate(days)
                ]
            )
            for month in range(0, YEARS * 12, 3):  # a purchase every quarter
                year, m = divmod(start.month - 1 + month, 12)
                db.add(
                    LedgerTransaction(
                        account_id=account.id,
                        instrument_id=instrument.id,
                        type="buy",
                        trade_date=date(start.year + year, m + 1, 3),
                        quantity=Decimal(5 + n % 4),
                        price=Decimal(50 + n),
                        fees=Decimal(1),
                    )
                )
        db.commit()
    clear_cache()
    return client


ENDPOINTS = [
    ("GET", "/api/v1/portfolio/history", None),
    ("GET", "/api/v1/portfolio/returns?period=5Y", None),
    ("GET", "/api/v1/portfolio/allocation?group_by=sector", None),
    ("GET", "/api/v1/portfolio/attribution?period=1Y", None),
    ("GET", "/api/v1/portfolio/risk?window=1Y", None),
    ("GET", "/api/v1/portfolio/returns/instruments?period=1Y", None),
]


def test_cached_dashboard_requests_stay_under_300_ms_at_p95(seeded: TestClient) -> None:
    def call(path: str) -> float:
        sep = "&" if "?" in path else "?"
        started = time.perf_counter()
        r = seeded.get(f"{path}{sep}as_of={AS_OF.isoformat()}")
        elapsed = time.perf_counter() - started
        assert r.status_code == 200, r.text
        return elapsed

    first = call("/api/v1/portfolio/allocation?group_by=sector")  # builds the context
    assert first < 60, f"the first build took {first:.1f} s"
    print(f"\nfirst request (context build): {first:.2f} s")

    timings = [call(path) for _, path, _ in ENDPOINTS]  # each one's first, uncached derivation
    for (_, path, _), took in zip(ENDPOINTS, timings, strict=True):
        print(f"  {path}: {took * 1000:.0f} ms")
    timings += [call(path) for _ in range(5) for _, path, _ in ENDPOINTS]
    timings.sort()
    p95 = timings[max(0, int(len(timings) * 0.95) - 1)]
    print(
        f"cached requests: median {statistics.median(timings) * 1000:.0f} ms, p95 {p95 * 1000:.0f} ms"
    )
    assert p95 < 0.3, f"p95 was {p95 * 1000:.0f} ms"
