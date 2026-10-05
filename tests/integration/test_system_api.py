"""System page endpoints: provider usage, jobs and the audit viewer (FR-MD-10, FR-SY-08)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models_ledger import JobRequest, PortfolioSnapshot, PriceBar
from folio.jobs.market import fx_job
from folio.jobs.scheduler import JOB_PARAMS, process_job_requests
from folio.marketdata.fake import FakeProvider
from folio.marketdata.runtime import make_usage_tracker
from tests.conftest import FAKE_API_KEY, PASSWORD, USERNAME
from tests.marketdata_helpers import bars_for, make_ctx, make_listing

D = Decimal


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


@pytest.fixture
def api(client: TestClient, owner: None) -> TestClient:
    client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return client


def test_requires_login(client: TestClient) -> None:
    for path in ("/api/v1/system/usage", "/api/v1/system/jobs", "/api/v1/audit"):
        assert client.get(path).status_code == 401
    assert client.post("/api/v1/system/jobs/fx/run", json={}).status_code == 401


# --- provider usage (FR-MD-10) -----------------------------------------------------------------


def test_usage_shows_todays_calls_against_the_budgets(api: TestClient, settings: Settings) -> None:
    tracker = make_usage_tracker(make_session_factory(make_engine(settings.db_url)))
    for _ in range(3):
        tracker.charge("eodhd")  # budget 20 by default
    tracker.charge("yahoo")
    tracker.charge("yahoo")
    rows = {r["provider"]: r for r in api.get("/api/v1/system/usage").json()}
    assert rows["eodhd"]["calls_today"] == 3 and rows["eodhd"]["daily_budget"] == 20
    assert rows["eodhd"]["remaining"] == 17  # matches the counter exactly
    assert rows["yahoo"]["calls_today"] == 2 and rows["yahoo"]["daily_budget"] is None
    assert rows["yahoo"]["remaining"] is None and rows["yahoo"]["enabled"] is True
    assert rows["twelvedata"]["calls_today"] == 0 and rows["twelvedata"]["daily_budget"] == 800
    assert set(rows) >= {"eodhd", "yahoo", "twelvedata", "openfigi", "ecb", "fred"}


def test_usage_says_whether_a_key_is_saved_without_showing_it(api: TestClient) -> None:
    rows = {r["provider"]: r for r in api.get("/api/v1/system/usage").json()}
    assert rows["eodhd"]["has_key"] is False and rows["yahoo"]["has_key"] is None
    assert rows["ecb"]["has_key"] is None
    api.put("/api/v1/settings/providers", json={"eodhd_api_key": FAKE_API_KEY})
    rows = {r["provider"]: r for r in api.get("/api/v1/system/usage").json()}
    assert rows["eodhd"]["has_key"] is True
    assert FAKE_API_KEY not in str(rows)


def test_a_budget_change_in_settings_shows_up(api: TestClient) -> None:
    body = api.get("/api/v1/settings/providers").json()
    body["providers"]["eodhd"]["daily_call_budget"] = 100
    for key in ("eodhd_api_key", "twelvedata_api_key", "openfigi_api_key", "fred_api_key"):
        body.pop(key)
    assert api.put("/api/v1/settings/providers", json=body).status_code == 200
    rows = {r["provider"]: r for r in api.get("/api/v1/system/usage").json()}
    assert rows["eodhd"]["daily_budget"] == 100 and rows["eodhd"]["remaining"] == 100


# --- jobs --------------------------------------------------------------------------------------


def test_job_runs_are_listed_newest_first_with_their_log(
    api: TestClient, settings: Settings
) -> None:
    ctx = make_ctx(settings, [], now=datetime(2024, 1, 15, 12, tzinfo=UTC))
    fx_job(ctx)
    fx_job(ctx)
    body = api.get("/api/v1/system/jobs").json()
    runs = body["runs"]
    assert [r["job"] for r in runs] == ["fx", "fx"] and runs[0]["id"] > runs[1]["id"]
    assert runs[0]["status"] == "ok" and "No foreign currency" in runs[0]["log"]
    assert runs[0]["duration_seconds"] is not None and runs[0]["duration_seconds"] >= 0
    assert body["available"]["backfill"] == ["listing_id"] and body["available"]["fx"] == []
    assert set(body["available"]) == set(JOB_PARAMS)
    assert len(api.get("/api/v1/system/jobs?limit=1").json()["runs"]) == 1


def test_a_job_can_be_requested_and_the_worker_picks_it_up(
    api: TestClient, settings: Settings, db
) -> None:  # type: ignore[no-untyped-def]
    r = api.post("/api/v1/system/jobs/fx/run", json={})
    assert r.status_code == 202
    queued = r.json()
    assert (queued["job"], queued["status"], queued["params"]) == ("fx", "pending", {})
    assert [x["status"] for x in api.get("/api/v1/system/jobs").json()["requests"]] == ["pending"]

    process_job_requests(make_ctx(settings, []), settings)  # what the worker does within seconds
    after = api.get("/api/v1/system/jobs").json()
    assert (
        after["requests"][0]["status"] == "done" and after["requests"][0]["finished_at"] is not None
    )
    assert [x["job"] for x in after["runs"]] == ["fx"]


def test_requested_jobs_are_validated(api: TestClient, db) -> None:  # type: ignore[no-untyped-def]
    unknown = api.post("/api/v1/system/jobs/make-coffee/run", json={})
    assert unknown.status_code == 404 and "Jobs:" in unknown.json()["detail"]
    missing = api.post("/api/v1/system/jobs/backfill/run", json={})
    assert missing.status_code == 422 and "needs: listing_id" in missing.json()["detail"]
    ok = api.post("/api/v1/system/jobs/backfill/run", json={"params": {"listing_id": 7, "junk": 1}})
    assert ok.status_code == 202 and ok.json()["params"] == {
        "listing_id": 7
    }  # only known parameters are kept
    assert db.query(JobRequest).count() == 1


def test_refresh_prices_now_fetches_closes_and_redoes_the_recent_snapshots(
    api: TestClient, settings: Settings, db
) -> None:  # type: ignore[no-untyped-def]
    instrument, listing = make_listing(db)
    db.commit()
    account = api.post("/api/v1/accounts", json={"name": "A"}).json()["id"]
    api.post("/api/v1/transactions", json={"account_id": account, "instrument_id": instrument.id,
             "type": "buy", "trade_date": "2024-01-02", "quantity": "10", "price": "100"})  # fmt: skip
    db.query(JobRequest).delete()
    db.commit()
    provider = FakeProvider(
        name="p", bars={listing.id: bars_for("XETR", date(2023, 12, 20), date(2024, 1, 12))}
    )
    ctx = make_ctx(settings, [provider], now=datetime(2024, 1, 12, 18, tzinfo=UTC))
    assert api.post("/api/v1/system/jobs/refresh/run", json={}).status_code == 202
    assert process_job_requests(ctx, settings) == 1
    db.expire_all()
    closes = db.scalars(select(PriceBar).where(PriceBar.listing_id == listing.id)).all()
    assert closes and max(c.date for c in closes) == date(2024, 1, 12)
    jobs = [j["job"] for j in api.get("/api/v1/system/jobs").json()["runs"]]
    # newest first: the closes, then the values they change, then the rules they may breach
    assert jobs == ["rules", "snapshots", "refresh"]
    assert db.query(PortfolioSnapshot).count() >= 10


def test_refresh_with_nothing_tracked_says_so(api: TestClient, settings: Settings) -> None:
    api.post("/api/v1/system/jobs/refresh/run", json={})
    process_job_requests(make_ctx(settings, []), settings)
    refresh = next(
        r for r in api.get("/api/v1/system/jobs").json()["runs"] if r["job"] == "refresh"
    )
    assert refresh["status"] == "ok" and "Nothing is tracked yet" in refresh["log"]


# --- the audit viewer (FR-SY-08) ----------------------------------------------------------------


def seed_changes(api: TestClient) -> dict[str, Any]:
    account = api.post("/api/v1/accounts", json={"name": "Degiro"}).json()
    api.patch(f"/api/v1/accounts/{account['id']}", json={"name": "Degiro NL"})
    manual = api.post(
        "/api/v1/instruments",
        json={"name": "Private bond", "asset_class": "BOND", "manual": True, "currency": "EUR"},
    ).json()
    api.patch(f"/api/v1/instruments/{manual['id']}", json={"name": "Private bond 2030"})
    api.put("/api/v1/settings/appearance", json={"theme": "dark"})
    return {"account": account["id"], "instrument": manual["id"]}


def test_every_change_shows_old_and_new_values(api: TestClient) -> None:
    ids = seed_changes(api)
    page = api.get("/api/v1/audit").json()
    items = page["items"]
    assert (
        items == sorted(items, key=lambda i: i["id"], reverse=True) and page["next_cursor"] is None
    )
    rename = next(i for i in items if i["entity"] == "account" and i["action"] == "update")
    assert rename["entity_id"] == str(ids["account"]) and rename["actor"] == "user"
    assert rename["diff"]["name"] == {"old": "Degiro", "new": "Degiro NL"}
    edit = next(i for i in items if i["entity"] == "instrument" and i["action"] == "update")
    assert edit["diff"]["name"] == {"old": "Private bond", "new": "Private bond 2030"}
    theme = next(i for i in items if i["entity"] == "setting")
    assert theme["entity_id"] == "appearance" and theme["diff"]["theme"] == {
        "old": "system",
        "new": "dark",
    }
    assert all(i["ts"] for i in items)


def test_the_audit_log_can_be_filtered(api: TestClient) -> None:
    ids = seed_changes(api)

    def get(**params: Any) -> list[dict[str, Any]]:
        return api.get("/api/v1/audit", params=params).json()["items"]  # type: ignore[no-any-return]

    assert {i["entity"] for i in get(entity="account")} == {"account"}
    assert [i["action"] for i in get(entity="account", entity_id=str(ids["account"]))] == [
        "update",
        "create",
    ]
    assert {i["action"] for i in get(action="create")} == {"create"}
    assert {i["actor"] for i in get(actor="user")} == {"user"} and get(actor="worker") == []
    today = datetime.now(UTC).date().isoformat()  # the log stamps UTC; local midnight differs
    assert len(get(**{"from": today, "to": today})) == len(get())  # everything happened today
    assert get(**{"from": "2999-01-01"}) == [] and get(to="2000-01-01") == []
    assert get(entity="nothing") == []


def test_the_audit_log_is_paged_newest_first(api: TestClient) -> None:
    seed_changes(api)
    total = len(api.get("/api/v1/audit?limit=500").json()["items"])
    assert total >= 5
    seen: list[int] = []
    cursor = None
    while True:
        params: dict[str, Any] = {"limit": 2}
        if cursor is not None:
            params["cursor"] = cursor
        page = api.get("/api/v1/audit", params=params).json()
        seen += [i["id"] for i in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == total == len(set(seen)) and seen == sorted(seen, reverse=True)


def test_the_audit_log_is_append_only(api: TestClient) -> None:
    for method, path in (
        ("delete", "/api/v1/audit/1"),
        ("put", "/api/v1/audit/1"),
        ("post", "/api/v1/audit"),
    ):
        assert api.request(method.upper(), path).status_code in (404, 405)  # no way to change it
