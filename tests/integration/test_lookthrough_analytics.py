# ruff: noqa: F811  (the fixtures are imported from test_portfolio and used as parameters)
"""Look-through on stored data (FR-PF-05): the allocation endpoint, the top-exposures endpoint,
the dashboard widgets and the What-if simulator, on the book of tests/integration/test_portfolio.py
(fund F, 11 units, worth 1188 on 15 Jan 2024) plus a direct share and a second fund."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from folio.analytics_service import clear_cache
from folio.db.models_ledger import PriceBar
from folio.lookthrough.parse import Constituent, HoldingsRead
from folio.lookthrough.service import store_snapshot
from tests.integration.test_dashboards_api import data, one
from tests.integration.test_portfolio import api, book, db, tx  # noqa: F401
from tests.marketdata_helpers import bars_for, make_listing

D = Decimal
AS_OF = "2024-01-15"
ALPHA_ISIN = "US0000000001"


@pytest.fixture(autouse=True)
def fresh_cache() -> None:
    clear_cache()


def snapshot(db, instrument_id: int, *rows: tuple[str, str, str | None]) -> None:  # type: ignore[no-untyped-def]
    constituents = [
        Constituent(name=n, weight_pct=D(w), isin=i, sector="Information Technology")
        for n, w, i in rows
    ]
    read = HoldingsRead(constituents, sum((c.weight_pct for c in constituents), D(0)))
    store_snapshot(db, instrument_id, read, date(2024, 1, 5), "csv")
    db.commit()
    clear_cache()


@pytest.fixture
def three_wrappers(api: TestClient, db, book) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """Alpha Inc held directly (1 080), inside fund F (10 % of 1 188) and inside fund G (20 % of
    540): one company, three places."""
    alpha, alpha_listing = make_listing(db, ticker="ALPHA", isin=ALPHA_ISIN)
    alpha.name, alpha.asset_class = "Alpha Inc", "EQUITY"
    second, second_listing = make_listing(db, ticker="G", isin="IE0000000099")
    second.name = "G fund"
    for listing in (alpha_listing, second_listing):
        for bar in bars_for("XETR", date(2024, 1, 1), date(2024, 1, 12)):
            db.add(PriceBar(listing_id=listing.id, date=bar.date, close=bar.close, source="x"))
    db.commit()
    for instrument, units in ((alpha, "10"), (second, "5")):
        tx(
            api,
            account_id=book["account"],
            instrument_id=instrument.id,
            type="buy",
            trade_date="2024-01-02",
            quantity=units,
            price="100",
        )
    snapshot(db, book["fund"], ("ALPHA INC", "10", ALPHA_ISIN), ("BETA CORP", "60", None))
    snapshot(db, second.id, ("Alpha Inc.", "20", ALPHA_ISIN), ("GAMMA SA", "70", None))
    return {**book, "alpha": alpha.id, "second": second.id}


# --- the endpoints ------------------------------------------------------------------------------


def test_without_holdings_an_etf_is_shown_as_itself(api: TestClient, book) -> None:
    out = api.get("/api/v1/portfolio/look-through", params={"as_of": AS_OF}).json()
    assert out["opened"] == [] and out["unopened"] == ["F fund"]
    assert [(e["key"], e["value_eur"]) for e in out["exposures"]] == [("F fund", "1188")]
    assert out["exposures"][0]["parts"][0]["kind"] == "fund"


def test_a_company_in_three_places_is_one_exposure_with_its_breakdown(
    api: TestClient, three_wrappers
) -> None:
    out = api.get("/api/v1/portfolio/look-through", params={"as_of": AS_OF}).json()
    assert out["total_eur"] == "2808" and out["unopened"] == []
    assert {o["name"] for o in out["opened"]} == {"F fund", "G fund"}
    alpha = out["exposures"][0]
    assert (alpha["key"], D(alpha["value_eur"])) == ("Alpha Inc", D("1306.8"))  # 1080+118.8+108
    assert D(alpha["weight"]) == D("1306.8") / 2808 or abs(D(alpha["weight"]) - D("0.4653846")) < D(
        "1e-6"
    )
    where = {(p["source"], p["kind"]): (D(p["value_eur"]), p["weight_pct"]) for p in alpha["parts"]}
    assert where == {
        ("Alpha Inc", "direct"): (D(1080), None),
        ("F fund", "look_through"): (D("118.8"), "10"),
        ("G fund", "look_through"): (D(108), "20"),
    }


def test_top_limits_the_list_and_reports_what_is_below_it(api: TestClient, three_wrappers) -> None:
    out = api.get("/api/v1/portfolio/look-through", params={"as_of": AS_OF, "top": 1}).json()
    assert [e["key"] for e in out["exposures"]] == ["Alpha Inc"]
    assert abs(D(out["rest_weight"]) - (1 - D("1306.8") / 2808)) < D("1e-9")


def test_sectors_group_what_the_files_state_and_the_rest_is_unclassified(
    api: TestClient, three_wrappers
) -> None:
    by_sector = api.get(
        "/api/v1/portfolio/look-through", params={"as_of": AS_OF, "dimension": "sector"}
    ).json()
    values = {e["key"]: D(e["value_eur"]) for e in by_sector["exposures"]}
    # F states 70 % of its 1 188, G 90 % of its 540; the direct share and the unnamed rest of
    # each fund (356.4 and 54) have no sector in the files
    assert values == {"Information Technology": D("1317.6"), "Unclassified": D("1490.4")}


def test_the_allocation_endpoint_opens_etfs_only_when_asked(
    api: TestClient, three_wrappers
) -> None:
    plain = api.get("/api/v1/portfolio/allocation", params={"as_of": AS_OF}).json()
    assert plain["look_through"] is False and plain["slices"][0]["parts"] == []
    opened = api.get(
        "/api/v1/portfolio/allocation",
        params={"as_of": AS_OF, "group_by": "company", "look_through": True},
    ).json()
    assert opened["look_through"] is True
    assert (opened["slices"][0]["key"], len(opened["slices"][0]["parts"])) == ("Alpha Inc", 3)
    needs = api.get("/api/v1/portfolio/allocation", params={"group_by": "company"})
    assert needs.status_code == 422 and "needs look_through=true" in needs.json()["detail"]
    wrong = api.get(
        "/api/v1/portfolio/allocation", params={"group_by": "sleeve", "look_through": True}
    )
    assert (
        wrong.status_code == 422
        and "company, sector, country or currency" in wrong.json()["detail"]
    )


# --- the What-if simulator ----------------------------------------------------------------------


def test_the_simulator_shows_company_exposure_before_and_after(
    api: TestClient, three_wrappers
) -> None:
    body = {
        "as_of": AS_OF,
        "trades": [{"instrument_id": three_wrappers["second"], "side": "buy", "quantity": "5"}],
    }
    shown = api.post("/api/v1/portfolio/simulate", json=body).json()
    alpha = next(r for r in shown["look_through"] if r["label"] == "Alpha Inc")
    assert D(alpha["after_eur"]) - D(alpha["before_eur"]) == D(
        108
    )  # 5 more units of G: 20 % of 540
    assert D(alpha["after_weight"]) != D(alpha["before_weight"])
    assert not any("Other holdings" in r["label"] for r in shown["look_through"])
    assert len(shown["look_through"]) <= 15


def test_the_simulator_says_nothing_about_look_through_without_holdings(
    api: TestClient, book
) -> None:
    body = {
        "as_of": AS_OF,
        "trades": [{"instrument_id": book["fund"], "side": "buy", "quantity": "1"}],
    }
    assert api.post("/api/v1/portfolio/simulate", json=body).json()["look_through"] == []


# --- the dashboard widgets ----------------------------------------------------------------------


def test_the_look_through_widget_shows_the_top_companies(api: TestClient, three_wrappers) -> None:
    out = one(api, "look_through", {"dimension": "company", "top_n": 2})
    assert [s["key"] for s in out["slices"]][0] == "Alpha Inc" and len(out["slices"]) == 2
    assert out["slices"][0]["parts"][0]["source"] == "Alpha Inc"
    assert {o["name"] for o in out["opened"]} == {"F fund", "G fund"}
    assert D(out["rest_weight"]) > 0


def test_the_look_through_widget_explains_what_is_missing(api: TestClient, book) -> None:
    out = one(api, "look_through")
    assert out["empty"] is True and "holdings file" in out["reason"]


def test_the_allocation_widget_can_look_through(api: TestClient, three_wrappers) -> None:
    out = one(api, "allocation", {"group_by": "company", "look_through": True})
    assert out["look_through"] is True and out["slices"][0]["key"] == "Alpha Inc"
    bad = data(api, {"w": ("allocation", {"group_by": "sleeve", "look_through": True})})["w"]
    assert "company, sector, country or currency" in bad["error"]
    bad = data(api, {"w": ("allocation", {"group_by": "company"})})["w"]
    assert "needs look-through switched on" in bad["error"]
