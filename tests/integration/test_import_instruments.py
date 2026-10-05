"""A first import into an empty Folio: the review offers to add the instruments the file names,
looked up by ISIN on the exchange the export names, or by hand (FR-TX-07, "map instruments by
ISIN"). Found by the owner: every row of a real Degiro export was refused with "is not added
yet. Add the instrument first.", with no way forward from the wizard."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from tenacity import wait_none

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models_ledger import Instrument, JobRequest, Listing
from folio.imports.instruments import Missing, pick_listing
from folio.marketdata.resolve import Candidate
from tests.conftest import PASSWORD, USERNAME
from tests.integration.test_imports_api import preview
from tests.integration.test_instruments_api import provider_handler
from tests.marketdata_helpers import Scripted

FILE = "degiro_transactions_2026.csv"


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


@pytest.fixture
def api(make_client: Callable[..., TestClient], owner: None) -> TestClient:
    client = make_client(
        provider_transport=Scripted(provider_handler).transport,
        provider_http_options={"wait": wait_none()},
    )
    client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return client


def review(api: TestClient) -> tuple[int, dict[str, Any]]:
    account = api.post("/api/v1/accounts", json={"name": "Degiro"}).json()["id"]
    p = preview(api, account, name=FILE)
    batch = p["batch"]["id"]
    r = api.put(f"/api/v1/imports/{batch}/mapping", json={"mapping": p["mapping"]})
    assert r.status_code == 200, r.text
    return batch, r.json()


def test_the_review_says_what_the_file_knows_about_each_missing_instrument(api: TestClient) -> None:
    _, dry = review(api)
    assert dry["counts"]["error"] == 4 and dry["can_commit"] is False
    assert dry["missing"] == [
        {
            "isin": "IE00B5BMR087",
            "name": "ISHARES CORE S&P 500 UCITS ETF",
            "exchange": "XETR",
            "currency": "EUR",
            "rows": 2,
        },
        {
            "isin": "US0378331005",
            "name": "APPLE INC",
            "exchange": "XNYS",
            "currency": "USD",
            "rows": 2,
        },
    ]


def test_missing_instruments_are_added_by_lookup_then_by_hand_and_the_import_goes_through(
    api: TestClient, db
) -> None:  # type: ignore[no-untyped-def]
    batch, _ = review(api)
    r = api.post(f"/api/v1/imports/{batch}/instruments", json={})
    assert r.status_code == 200, r.text
    looked_up = {x["isin"]: x for x in r.json()["results"]}
    # the S&P fund: found by its ISIN, on Xetra as the export says, priced in EUR
    assert looked_up["IE00B5BMR087"]["status"] == "added"
    assert looked_up["IE00B5BMR087"]["detail"] == "Xetra · SXR8 · EUR"
    # Apple is unknown to the recorded lookup: nothing is guessed, the reason is given
    assert looked_up["US0378331005"]["status"] == "failed"
    assert "add it by hand" in looked_up["US0378331005"]["detail"]
    after = r.json()["dry_run"]
    assert (after["counts"]["new"], after["counts"]["error"]) == (2, 2)
    assert [m["isin"] for m in after["missing"]] == ["US0378331005"]

    by_hand = api.post(f"/api/v1/imports/{batch}/instruments", json={"by_hand": True}).json()
    assert by_hand["results"] == [
        {
            "isin": "US0378331005",
            "name": "APPLE INC",
            "status": "manual",
            "detail": "hand-priced in USD",
        }
    ]
    final = by_hand["dry_run"]
    assert final["counts"] == {"new": 4, "duplicate": 0, "error": 0, "skipped": 0}
    assert final["can_commit"] is True and final["missing"] == []
    assert api.post(f"/api/v1/imports/{batch}/commit", json={}).json()["rows_imported"] == 4

    fund = db.scalar(select(Instrument).where(Instrument.isin == "IE00B5BMR087"))
    listing = db.scalar(select(Listing).where(Listing.instrument_id == fund.id))
    assert (listing.exchange_mic, listing.ticker, listing.currency) == ("XETR", "SXR8", "EUR")
    backfills = db.scalars(select(JobRequest).where(JobRequest.job == "backfill")).all()
    assert [b.params for b in backfills] == [{"listing_id": listing.id}]  # prices follow


def candidate(mic: str, currency: str, usable: bool = True, confirmed: bool = True) -> Candidate:
    return Candidate(mic, mic, f"T{mic}", currency, confirmed, None, "figi", {}, usable)


def test_the_listing_follows_the_export_then_the_trade_currency() -> None:
    xetra, amsterdam, london = (
        candidate("XETR", "EUR"),
        candidate("XAMS", "EUR"),
        candidate("XLON", "USD"),
    )
    wants_amsterdam = Missing("X", "", "XAMS", "EUR", 1)
    assert pick_listing([xetra, amsterdam, london], wants_amsterdam) is amsterdam
    no_exchange = Missing("X", "", None, "USD", 1)
    assert pick_listing([xetra, london], no_exchange) is london
    unknown_exchange = Missing("X", "", "XTSE", "CAD", 1)
    assert pick_listing([xetra, london], unknown_exchange) is xetra  # the first usable
    assert pick_listing([candidate("XLON", "GBX", usable=False)], unknown_exchange) is None
