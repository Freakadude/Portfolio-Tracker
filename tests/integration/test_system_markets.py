"""Opening hours of the markets the portfolio trades on (System page)."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from folio.marketdata import exchanges
from tests.integration.test_classification_api import api, db  # noqa: F401
from tests.marketdata_helpers import make_listing


def test_a_trading_day_has_hours_and_is_open_between_them() -> None:
    tuesday = datetime(2025, 12, 16, 10, 0, tzinfo=UTC)  # 11:00 in Frankfurt
    hours = exchanges.market_hours("XETR", tuesday)
    assert hours.open_now is True and hours.timezone == "Europe/Berlin"
    assert hours.opens == datetime(2025, 12, 16, 8, 0, tzinfo=UTC)  # 09:00 local
    assert hours.closes == datetime(2025, 12, 16, 16, 30, tzinfo=UTC)  # 17:30 local
    assert hours.next_open == datetime(2025, 12, 17, 8, 0, tzinfo=UTC)


def test_a_weekend_has_no_hours_and_names_the_next_opening() -> None:
    saturday = datetime(2025, 12, 20, 12, 0, tzinfo=UTC)
    hours = exchanges.market_hours("XETR", saturday)
    assert (hours.open_now, hours.opens, hours.closes) == (False, None, None)
    assert hours.next_open == datetime(2025, 12, 22, 8, 0, tzinfo=UTC)


def test_new_york_hours_follow_its_own_clock_and_daylight_saving() -> None:
    summer = exchanges.market_hours("XNYS", datetime(2025, 7, 1, 12, 0, tzinfo=UTC))
    assert summer.opens == datetime(2025, 7, 1, 13, 30, tzinfo=UTC)  # 09:30 EDT
    winter = exchanges.market_hours("XNYS", datetime(2025, 12, 16, 12, 0, tzinfo=UTC))
    assert winter.opens == datetime(2025, 12, 16, 14, 30, tzinfo=UTC)  # 09:30 EST


def test_the_page_lists_only_the_markets_of_what_you_hold_or_watch(
    api: TestClient,  # noqa: F811
    db,  # type: ignore[no-untyped-def]  # noqa: F811
) -> None:
    assert api.get("/api/v1/system/markets").json() == []  # nothing held, nothing watched
    held, _ = make_listing(db, ticker="H", mic="XETR", isin="IE00B5BMR087")
    watched, _ = make_listing(db, ticker="W", mic="XNYS", currency="USD", isin="US0378331005")
    db.commit()
    account = api.post("/api/v1/accounts", json={"name": "Degiro"}).json()["id"]
    api.post(
        "/api/v1/transactions",
        json={
            "account_id": account,
            "instrument_id": held.id,
            "type": "buy",
            "trade_date": "2024-01-02",
            "quantity": "1",
            "price": "100",
        },
    )
    wl = api.get("/api/v1/watchlists").json()[0]
    api.post(f"/api/v1/watchlists/{wl['id']}/items", json={"instrument_id": watched.id})

    markets = {m["mic"]: m for m in api.get("/api/v1/system/markets").json()}
    assert set(markets) == {"XETR", "XNYS"}
    assert markets["XETR"]["holdings"] == [held.name] and markets["XETR"]["watching"] == []
    assert markets["XNYS"]["holdings"] == [] and markets["XNYS"]["watching"] == [watched.name]
    assert markets["XETR"]["timezone"] == "Europe/Berlin" and markets["XETR"]["next_open"]
