"""Classification, sleeves and watchlists (FR-INS-04, FR-INS-05, FR-MD-12)."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import AuditLog
from folio.db.models_ledger import JobRequest, PriceBar
from folio.marketdata.prices import tracked_listings
from folio.marketdata.quotes import held_listings
from tests.conftest import PASSWORD, USERNAME
from tests.marketdata_helpers import make_listing

D = Decimal


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


@pytest.fixture
def api(client: TestClient, owner: None) -> TestClient:
    client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return client


def manual(api: TestClient, name: str = "Private bond", **extra: Any) -> dict[str, Any]:
    body = {"name": name, "asset_class": "BOND", "manual": True, "currency": "EUR", **extra}
    r = api.post("/api/v1/instruments", json=body)
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def sleeve(api: TestClient, name: str = "us_equity", **extra: Any) -> dict[str, Any]:
    r = api.post("/api/v1/sleeves", json={"name": name, **extra})
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


# --- classification -----------------------------------------------------------------------------


def test_an_instrument_can_be_classified_and_flagged_as_a_benchmark(api: TestClient) -> None:
    s = sleeve(api)
    instrument = manual(api)
    assert (instrument["region"], instrument["sector"], instrument["sleeve_id"]) == (
        None,
        None,
        None,
    )
    assert instrument["is_benchmark"] is False

    r = api.patch(
        f"/api/v1/instruments/{instrument['id']}",
        json={
            "region": "Europe",
            "sector": "Financials",
            "sleeve_id": s["id"],
            "is_benchmark": True,
        },
    )
    assert r.status_code == 200, r.text
    got = r.json()
    assert (got["region"], got["sector"], got["sleeve_id"], got["is_benchmark"]) == (
        "Europe",
        "Financials",
        s["id"],
        True,
    )
    assert api.get("/api/v1/sleeves").json()[0]["instrument_count"] == 1


def test_classification_changes_are_audited_with_old_and_new(api: TestClient, db) -> None:  # type: ignore[no-untyped-def]
    instrument = manual(api)
    api.patch(f"/api/v1/instruments/{instrument['id']}", json={"region": "US"})
    api.patch(f"/api/v1/instruments/{instrument['id']}", json={"region": "Europe"})
    diffs = [
        row.diff
        for row in db.scalars(select(AuditLog).where(AuditLog.entity == "instrument"))
        if row.action == "update"
    ]
    assert {"region": {"old": None, "new": "US"}} in diffs
    assert {"region": {"old": "US", "new": "Europe"}} in diffs


def test_an_unknown_sleeve_is_refused_in_plain_words(api: TestClient) -> None:
    instrument = manual(api)
    r = api.patch(f"/api/v1/instruments/{instrument['id']}", json={"sleeve_id": 999})
    assert r.status_code == 422
    assert "sleeve does not exist" in r.json()["detail"]
    created = api.post(
        "/api/v1/instruments",
        json={
            "name": "X",
            "asset_class": "BOND",
            "manual": True,
            "currency": "EUR",
            "sleeve_id": 999,
        },
    )
    assert created.status_code == 422


def test_a_new_instrument_can_carry_its_classification(api: TestClient) -> None:
    s = sleeve(api, "gold_hedge")
    got = manual(api, "Gold", region="Global", sector="Commodities", sleeve_id=s["id"])
    assert (got["region"], got["sector"], got["sleeve_id"]) == ("Global", "Commodities", s["id"])


# --- sleeves ------------------------------------------------------------------------------------


def test_sleeves_have_optional_targets_and_keep_their_order(api: TestClient) -> None:
    a = sleeve(api, "us_equity", target_pct="40", band_pct="5")
    b = sleeve(api, "gold_hedge")
    assert (a["target_pct"], a["band_pct"]) == ("40", "5")
    assert b["target_pct"] is None  # Q3: targets come later
    r = api.put("/api/v1/sleeves/order", json={"ids": [b["id"], a["id"]]})
    assert [s["name"] for s in r.json()] == ["gold_hedge", "us_equity"]
    assert [s["name"] for s in api.get("/api/v1/sleeves").json()] == ["gold_hedge", "us_equity"]
    assert api.put("/api/v1/sleeves/order", json={"ids": [a["id"]]}).status_code == 422


def test_sleeve_names_are_unique_and_targets_stay_in_range(api: TestClient) -> None:
    sleeve(api, "us_equity")
    clash = api.post("/api/v1/sleeves", json={"name": "US_EQUITY"})
    assert clash.status_code == 409 and "already a sleeve" in clash.json()["detail"]
    assert api.post("/api/v1/sleeves", json={"name": "x", "target_pct": "120"}).status_code == 422


def test_editing_and_deleting_a_sleeve(api: TestClient, db) -> None:  # type: ignore[no-untyped-def]
    s = sleeve(api, "us_equity", target_pct="40")
    r = api.patch(f"/api/v1/sleeves/{s['id']}", json={"name": "us", "target_pct": "35"})
    assert (r.json()["name"], r.json()["target_pct"]) == ("us", "35")
    audit = [row.diff for row in db.scalars(select(AuditLog).where(AuditLog.entity == "sleeve"))]
    assert {
        "target_pct": {"old": "40", "new": "35"},
        "name": {"old": "us_equity", "new": "us"},
    } in audit

    instrument = manual(api)
    api.patch(f"/api/v1/instruments/{instrument['id']}", json={"sleeve_id": s["id"]})
    blocked = api.delete(f"/api/v1/sleeves/{s['id']}")
    assert blocked.status_code == 409 and "1 instrument" in blocked.json()["detail"]
    api.patch(f"/api/v1/instruments/{instrument['id']}", json={"sleeve_id": None})
    assert api.delete(f"/api/v1/sleeves/{s['id']}").status_code == 204
    assert api.get("/api/v1/sleeves").json() == []
    assert api.patch("/api/v1/sleeves/999", json={"name": "x"}).status_code == 404


# --- watchlist ----------------------------------------------------------------------------------


def test_the_first_visit_creates_an_empty_watchlist(api: TestClient) -> None:
    lists = api.get("/api/v1/watchlists").json()
    assert [(w["name"], w["items"]) for w in lists] == [("Watchlist", [])]
    assert len(api.get("/api/v1/watchlists").json()) == 1  # not created again


def test_a_watched_instrument_shows_its_latest_price_and_a_note(api: TestClient, db) -> None:  # type: ignore[no-untyped-def]
    instrument, listing = make_listing(db, ticker="W")
    for day, close in [(date(2024, 1, 2), "100"), (date(2024, 1, 3), "103")]:
        db.add(PriceBar(listing_id=listing.id, date=day, close=D(close), source="x"))
    db.commit()
    wl = api.get("/api/v1/watchlists").json()[0]
    r = api.post(
        f"/api/v1/watchlists/{wl['id']}/items",
        json={"instrument_id": instrument.id, "note": "wait"},
    )
    assert r.status_code == 201, r.text
    [item] = r.json()["items"]
    assert (item["name"], item["note"], item["ticker"]) == (instrument.name, "wait", "W")
    assert (item["close"], item["close_date"], item["previous_close"]) == (
        "103",
        "2024-01-03",
        "100",
    )

    changed = api.patch(
        f"/api/v1/watchlists/{wl['id']}/items/{item['id']}", json={"note": "buy dip"}
    )
    assert changed.json()["items"][0]["note"] == "buy dip"
    again = api.post(f"/api/v1/watchlists/{wl['id']}/items", json={"instrument_id": instrument.id})
    assert again.status_code == 409 and "already on this watchlist" in again.json()["detail"]
    gone = api.delete(f"/api/v1/watchlists/{wl['id']}/items/{item['id']}")
    assert gone.json()["items"] == []


def test_watched_instruments_are_priced_by_the_nightly_jobs(api: TestClient, db) -> None:  # type: ignore[no-untyped-def]
    """FR-INS-05: the jobs track every active priced instrument, held or not."""
    instrument, listing = make_listing(db, ticker="W")
    db.commit()
    wl = api.get("/api/v1/watchlists").json()[0]
    api.post(f"/api/v1/watchlists/{wl['id']}/items", json={"instrument_id": instrument.id})
    assert [x.id for x, _ in tracked_listings(db)] == [listing.id]  # no transaction in sight


def test_adding_an_instrument_without_prices_asks_the_worker_for_its_history(
    api: TestClient,
    db,  # type: ignore[no-untyped-def]
) -> None:
    """A watched item shows data soon after it is added, not only after the next nightly run."""
    instrument, listing = make_listing(db, ticker="W")
    db.commit()
    wl = api.get("/api/v1/watchlists").json()[0]
    added = api.post(f"/api/v1/watchlists/{wl['id']}/items", json={"instrument_id": instrument.id})
    assert (
        added.json()["items"][0]["fetching"] is True and added.json()["items"][0]["close"] is None
    )
    queued = db.scalars(select(JobRequest).where(JobRequest.job == "backfill")).all()
    assert [r.params["listing_id"] for r in queued] == [listing.id]
    # asking again does not queue a second backfill for the same listing
    again = api.post(f"/api/v1/watchlists/{wl['id']}/refresh")
    assert again.status_code == 202
    assert len(db.scalars(select(JobRequest).where(JobRequest.job == "backfill")).all()) == 1
    assert len(db.scalars(select(JobRequest).where(JobRequest.job == "refresh")).all()) == 1


def test_watched_instruments_get_intraday_quotes_like_holdings(api: TestClient, db) -> None:  # type: ignore[no-untyped-def]
    instrument, listing = make_listing(db, ticker="W")
    db.commit()
    assert held_listings(db) == []
    wl = api.get("/api/v1/watchlists").json()[0]
    api.post(f"/api/v1/watchlists/{wl['id']}/items", json={"instrument_id": instrument.id})
    assert [x.id for x, _ in held_listings(db)] == [listing.id]


def test_watchlist_management_and_deleting_a_watched_instrument(api: TestClient) -> None:
    instrument = manual(api)
    wl = api.get("/api/v1/watchlists").json()[0]
    api.post(f"/api/v1/watchlists/{wl['id']}/items", json={"instrument_id": instrument["id"]})
    assert (
        api.patch(f"/api/v1/watchlists/{wl['id']}", json={"name": "Ideas"}).json()["name"]
        == "Ideas"
    )
    second = api.post("/api/v1/watchlists", json={"name": "Later"})
    assert second.status_code == 201
    # deleting the instrument takes it off every list
    assert api.delete(f"/api/v1/instruments/{instrument['id']}").status_code == 204
    assert api.get("/api/v1/watchlists").json()[0]["items"] == []
    assert api.delete(f"/api/v1/watchlists/{second.json()['id']}").status_code == 204
    assert api.get("/api/v1/watchlists/999").status_code in (404, 405)
    assert api.post("/api/v1/watchlists/999/items", json={"instrument_id": 1}).status_code == 404
    unknown = api.post(f"/api/v1/watchlists/{wl['id']}/items", json={"instrument_id": 999})
    assert unknown.status_code == 404


def test_requires_login(client: TestClient) -> None:
    for path in ("/api/v1/sleeves", "/api/v1/watchlists"):
        assert client.get(path).status_code == 401
