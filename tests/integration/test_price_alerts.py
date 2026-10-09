"""Price alerts on held or watched instruments: fire once on crossing, re-arm when the price is
back, and reach the inbox (FR-INS-05)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import AuditLog
from folio.db.models_ledger import PriceBar
from folio.db.models_strategy import Notification, Signal
from folio.jobs.strategies import rules_job
from tests.conftest import PASSWORD, USERNAME
from tests.marketdata_helpers import make_ctx

D = Decimal


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


@pytest.fixture
def api(client: TestClient, owner: None) -> TestClient:
    client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return client


@pytest.fixture
def watched(api: TestClient) -> dict[str, Any]:
    r = api.post(
        "/api/v1/instruments",
        json={"name": "Watched Co", "asset_class": "EQUITY", "manual": True, "currency": "USD"},
    )
    instrument = r.json()
    price(api, instrument["id"], "2024-03-01", "100")
    return instrument  # type: ignore[no-any-return]


def price(api: TestClient, instrument_id: int, day: str, close: str) -> None:
    r = api.post(f"/api/v1/instruments/{instrument_id}/prices", json={"date": day, "close": close})
    assert r.status_code == 201, r.text


def alert(
    api: TestClient, instrument_id: int, condition: str, threshold: str, **extra: Any
) -> dict[str, Any]:
    r = api.post(
        "/api/v1/price-alerts",
        json={
            "instrument_id": instrument_id,
            "condition": condition,
            "threshold": threshold,
            **extra,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def inbox(api: TestClient) -> list[dict[str, Any]]:
    return api.get("/api/v1/notifications").json()["items"]  # type: ignore[no-any-return]


def test_an_alert_fires_once_on_crossing_and_again_after_it_clears(
    api: TestClient, watched
) -> None:  # type: ignore[no-untyped-def]
    a = alert(api, watched["id"], "above", "110", note="take a look")
    assert (a["armed"], a["met_now"], a["currency"], D(a["last_close"])) == (
        True,
        False,
        "USD",
        100,
    )

    price(api, watched["id"], "2024-03-04", "112")  # crosses: fires at once
    (item,) = inbox(api)
    assert (item["source"], item["severity"], item["subject"]) == ("alert", "high", "Watched Co")
    assert item["title"] == "Watched Co closed above 110.00 USD"
    assert "take a look" in item["body"] and item["link"] == f"/holdings/{watched['id']}"
    assert [d["channel"] for d in item["deliveries"]] == ["home_assistant", "ntfy"]  # high: pushed

    price(api, watched["id"], "2024-03-05", "115")  # still above: quiet
    assert len(inbox(api)) == 1
    price(api, watched["id"], "2024-03-06", "105")  # back below: re-armed
    assert api.get("/api/v1/price-alerts").json()[0]["armed"] is True
    price(api, watched["id"], "2024-03-07", "111")
    assert len(inbox(api)) == 2


def test_a_level_already_passed_waits_for_the_next_crossing(api: TestClient, watched) -> None:  # type: ignore[no-untyped-def]
    a = alert(api, watched["id"], "below", "120")  # 100 is already below 120
    assert (a["armed"], a["met_now"]) == (False, True)
    price(api, watched["id"], "2024-03-04", "99")
    assert inbox(api) == []
    changed = api.patch(f"/api/v1/price-alerts/{a['id']}", json={"threshold": "90"}).json()
    assert (changed["armed"], changed["met_now"]) == (True, False)
    price(api, watched["id"], "2024-03-05", "89")
    assert len(inbox(api)) == 1


def test_a_paused_or_deleted_alert_never_fires_and_changes_are_audited(
    api: TestClient, watched, db
) -> None:  # type: ignore[no-untyped-def]
    a = alert(api, watched["id"], "above", "110")
    api.patch(f"/api/v1/price-alerts/{a['id']}", json={"active": False})
    price(api, watched["id"], "2024-03-04", "120")
    assert inbox(api) == []
    assert api.delete(f"/api/v1/price-alerts/{a['id']}").status_code == 204
    assert api.get("/api/v1/price-alerts").json() == []
    actions = [
        r.action for r in db.scalars(select(AuditLog).where(AuditLog.entity == "price_alert"))
    ]
    assert actions == ["create", "update", "delete"]
    assert (
        api.post(
            "/api/v1/price-alerts",
            json={"instrument_id": 999, "condition": "above", "threshold": "1"},
        ).status_code
        == 404
    )


def test_the_nightly_closes_are_checked_by_the_rules_job(
    api: TestClient, watched, settings: Settings, db
) -> None:  # type: ignore[no-untyped-def]
    alert(api, watched["id"], "above", "110")
    listing_id = api.get(f"/api/v1/instruments/{watched['id']}").json()["listings"][0]["id"]
    db.add(PriceBar(listing_id=listing_id, date=date(2024, 3, 4), close=D(113), source="fake"))
    db.commit()
    result = rules_job(make_ctx(settings, [], now=datetime(2024, 3, 4, 20, tzinfo=UTC)))
    assert result.status == "ok" and "1 price alert(s) fired" in result.log
    db.expire_all()
    (signal,) = db.scalars(select(Signal)).all()
    assert (signal.rule_type, signal.state, signal.strategy_version_id) == (
        "price_alert",
        "consumed",
        None,
    )
    assert db.scalars(select(Notification)).one().source == "alert"
    assert (
        api.get(f"/api/v1/price-alerts?instrument_id={watched['id']}").json()[0]["last_fired_at"]
        is not None
    )
