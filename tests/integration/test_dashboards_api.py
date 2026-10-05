# ruff: noqa: F811  (the fixtures are imported from test_portfolio and used as parameters)
"""Dashboards, widgets, templates and live updates (FR-DB-01 to FR-DB-08), on the book of
tests/integration/test_portfolio.py: fund F bought on 2 Jan (10 @ 100, fee 1) and 8 Jan (5 @ 104),
a dividend of 3 on 10 Jan, 4 sold on 11 Jan; the last close is 108 on 12 Jan. At 15 Jan 2024:
value 1188, net contributions 1098, income 3, total result 93."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from folio.analytics_service import clear_cache
from folio.api.routers import events as events_router
from folio.dashboards.templates import TEMPLATES
from folio.db.models_analytics import AppEvent
from folio.db.models_ledger import PriceBar
from folio.events import publish_event
from folio.marketdata.fake import FakeProvider
from tests.integration.test_portfolio import api, book, db, tx  # noqa: F401
from tests.marketdata_helpers import bars_for, make_ctx, make_listing

D = Decimal
AS_OF = "2024-01-15"


@pytest.fixture(autouse=True)
def fresh_cache() -> None:
    clear_cache()


def make(api: TestClient, name: str = "Mine", template: str | None = None) -> dict[str, Any]:
    r = api.post("/api/v1/dashboards", json={"name": name, "template": template})
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def data(api: TestClient, widgets: dict[str, tuple[str, dict[str, Any]]], **filters: Any) -> Any:
    body = {
        "as_of": AS_OF,
        "filters": filters,
        "requests": [{"key": k, "type": t, "config": c} for k, (t, c) in widgets.items()],
    }
    r = api.post("/api/v1/widgets/data", json=body)
    assert r.status_code == 200, r.text
    return r.json()["results"]


def one(api: TestClient, kind: str, config: dict[str, Any] | None = None, **filters: Any) -> Any:
    result = data(api, {"w": (kind, config or {})}, **filters)["w"]
    assert result["error"] is None, result["error"]
    return result["data"]


# --- the dashboards (FR-DB-01) ------------------------------------------------------------------


def test_the_first_visit_creates_the_overview_and_makes_it_the_default(api) -> None:
    first = api.get("/api/v1/dashboards/default").json()
    assert (first["name"], first["is_default"]) == ("Overview", True)
    assert [w["type"] for w in first["widgets"]].count("kpi") == 4 and len(first["widgets"]) == 7
    assert api.get("/api/v1/dashboards/default").json()["id"] == first["id"]  # not created again
    assert len(api.get("/api/v1/dashboards").json()) == 1


def test_create_rename_duplicate_reorder_and_delete(api) -> None:
    a = make(api, "Risk review")
    b = make(api, "Risk review")
    assert (a["name"], b["name"]) == ("Risk review", "Risk review 2")  # names stay distinct
    assert a["is_default"] is True and b["is_default"] is False

    r = api.patch(f"/api/v1/dashboards/{b['id']}", json={"name": "Income view"})
    assert r.json()["name"] == "Income view"
    twin = api.post(f"/api/v1/dashboards/{a['id']}/duplicate")
    assert twin.status_code == 201 and twin.json()["name"] == "Risk review (copy)"

    order = [twin.json()["id"], b["id"], a["id"]]
    listed = api.put("/api/v1/dashboards/order", json={"ids": order}).json()
    assert [d["id"] for d in listed] == order
    assert [d["id"] for d in api.get("/api/v1/dashboards").json()] == order
    assert api.put("/api/v1/dashboards/order", json={"ids": [a["id"]]}).status_code == 422

    assert api.delete(f"/api/v1/dashboards/{a['id']}").status_code == 204
    assert api.get(f"/api/v1/dashboards/{a['id']}").status_code == 404
    # the default was deleted: the next one in order takes over
    assert api.get("/api/v1/dashboards/default").json()["id"] == twin.json()["id"]


def test_the_default_dashboard_can_be_chosen(api) -> None:
    a, b = make(api, "A"), make(api, "B")
    assert api.get("/api/v1/dashboards/default").json()["id"] == a["id"]
    api.post(f"/api/v1/dashboards/{b['id']}/default")
    assert api.get("/api/v1/dashboards/default").json()["id"] == b["id"]
    assert [d["is_default"] for d in api.get("/api/v1/dashboards").json()] == [False, True]


def test_a_duplicate_has_its_own_widgets_with_the_same_layout(api) -> None:
    original = make(api, "Overview", template="overview")
    copy = api.post(f"/api/v1/dashboards/{original['id']}/duplicate").json()
    assert {w["id"] for w in copy["widgets"]}.isdisjoint({w["id"] for w in original["widgets"]})
    shape = lambda d: sorted((w["type"], tuple(sorted(w["grid"].items()))) for w in d["widgets"])  # noqa: E731
    assert shape(copy) == shape(original)
    ids = {str(w["id"]) for w in copy["widgets"]}
    for bp in ("lg", "md", "sm"):
        assert {b["i"] for b in copy["layouts"][bp]} == ids


def test_bad_input_is_explained(api) -> None:
    assert api.post("/api/v1/dashboards", json={"name": "  "}).status_code == 422
    unknown = api.post("/api/v1/dashboards", json={"name": "X", "template": "nope"})
    assert unknown.status_code == 422 and "no template" in unknown.json()["detail"]
    assert api.get("/api/v1/dashboards/999").status_code == 404
    assert api.patch("/api/v1/dashboards/999", json={"name": "x"}).status_code == 404


# --- layouts per breakpoint (FR-DB-02, FR-DB-08) ------------------------------------------------


def test_a_layout_survives_a_reload_and_differs_per_breakpoint(api) -> None:
    d = make(api, "Overview", template="overview")
    ids = [str(w["id"]) for w in d["widgets"]]
    desktop = [{"i": i, "x": 0, "y": n * 2, "w": 12, "h": 2} for n, i in enumerate(ids)]
    phone = [
        {"i": i, "x": 0, "y": n * 3, "w": 1, "h": 3} for n, i in reversed(list(enumerate(ids)))
    ]
    r = api.put(
        f"/api/v1/dashboards/{d['id']}/layout", json={"layouts": {"lg": desktop, "sm": phone}}
    )
    assert r.status_code == 200, r.text
    again = api.get(f"/api/v1/dashboards/{d['id']}").json()
    assert {b["i"]: (b["w"], b["y"]) for b in again["layouts"]["lg"]} == {
        i: (12, n * 2) for n, i in enumerate(ids)
    }
    assert {b["i"]: b["y"] for b in again["layouts"]["sm"]} == {i: n * 3 for n, i in enumerate(ids)}
    assert all(b["w"] == 1 for b in again["layouts"]["sm"])
    assert again["layouts"]["lg"] != again["layouts"]["sm"]  # FR-DB-02
    assert {b["i"] for b in again["layouts"]["md"]} == set(ids)  # the tablet follows along
    # the widget rows hold the desktop box
    assert {w["grid"]["w"] for w in again["widgets"]} == {12}


def test_a_layout_that_cannot_be_drawn_is_refused_and_changes_nothing(api) -> None:
    d = make(api, "Overview", template="overview")
    before = api.get(f"/api/v1/dashboards/{d['id']}").json()["layouts"]
    wid = str(d["widgets"][0]["id"])
    for layouts, text in (
        ({"lg": [{"i": wid, "x": 10, "y": 0, "w": 6, "h": 2}]}, "12-column grid"),
        ({"lg": [{"i": "999", "x": 0, "y": 0, "w": 2, "h": 2}]}, "not on this dashboard"),
    ):
        r = api.put(f"/api/v1/dashboards/{d['id']}/layout", json={"layouts": layouts})
        assert r.status_code == 422 and text in r.json()["detail"]
    assert api.get(f"/api/v1/dashboards/{d['id']}").json()["layouts"] == before


def test_dashboard_filters_are_saved(api) -> None:
    d = make(api, "Mine")
    assert d["filters"] == {"period": "YTD", "account": None}
    r = api.patch(f"/api/v1/dashboards/{d['id']}", json={"filters": {"period": "1Y"}})
    assert r.json()["filters"] == {"period": "1Y", "account": None}


# --- widgets (FR-DB-03) -------------------------------------------------------------------------


def test_a_widget_can_be_added_configured_and_removed(api) -> None:
    d = make(api, "Mine")
    added = api.post(
        f"/api/v1/dashboards/{d['id']}/widgets", json={"type": "kpi", "config": {"metric": "xirr"}}
    )
    assert added.status_code == 201, added.text
    [widget] = added.json()["widgets"]
    assert widget["config"]["metric"] == "xirr" and widget["config"]["scope"]["kind"] == "portfolio"
    assert widget["grid"] == {"x": 0, "y": 0, "w": 3, "h": 3}  # the library's size
    second = api.post(f"/api/v1/dashboards/{d['id']}/widgets", json={"type": "allocation"}).json()
    assert second["widgets"][1]["grid"]["y"] == 3  # placed below, never on top

    path = f"/api/v1/dashboards/{d['id']}/widgets/{widget['id']}"
    changed = api.patch(path, json={"config": {"metric": "twr", "title": "Return"}})
    assert changed.json()["widgets"][0]["config"]["metric"] == "twr"
    assert changed.json()["widgets"][0]["config"]["title"] == "Return"
    gone = api.delete(path).json()
    assert [w["type"] for w in gone["widgets"]] == ["allocation"]
    assert all(b["i"] != str(widget["id"]) for bp in gone["layouts"].values() for b in bp)


def test_options_that_do_not_exist_are_refused(api) -> None:
    d = make(api, "Mine")
    bad = api.post(
        f"/api/v1/dashboards/{d['id']}/widgets", json={"type": "kpi", "config": {"metric": "fun"}}
    )
    assert bad.status_code == 422 and "kpi widget has an option" in bad.json()["detail"]
    unknown = api.post(f"/api/v1/dashboards/{d['id']}/widgets", json={"type": "clock"})
    assert unknown.status_code == 422 and "Unknown widget type" in unknown.json()["detail"]
    missing = api.patch(f"/api/v1/dashboards/{d['id']}/widgets/999", json={"config": {}})
    assert missing.status_code == 404


def test_the_widget_library_lists_all_nineteen(api) -> None:
    library = api.get("/api/v1/dashboard-widgets").json()
    assert len(library) == 19
    kpi = next(w for w in library if w["type"] == "kpi")
    assert (kpi["width"], kpi["height"], kpi["defaults"]["metric"]) == (3, 3, "value")


# --- templates (FR-DB-07) -----------------------------------------------------------------------


def test_the_four_templates_are_offered(api) -> None:
    listed = api.get("/api/v1/dashboard-templates").json()
    assert [t["key"] for t in listed] == ["overview", "risk", "income", "signals"]
    assert [t["name"] for t in listed] == ["Overview", "Risk", "Income", "Signals & news"]


@pytest.mark.parametrize("key", list(TEMPLATES))
def test_every_template_works_on_an_empty_portfolio(api, key) -> None:
    d = make(api, TEMPLATES[key].name, template=key)
    assert len(d["widgets"]) == len(TEMPLATES[key].widgets)
    results = data(api, {str(w["id"]): (w["type"], w["config"]) for w in d["widgets"]})
    assert len(results) == len(d["widgets"])
    assert all(r["error"] is None and r["data"] is not None for r in results.values()), results
    for bp in ("lg", "md", "sm"):
        assert len(d["layouts"][bp]) == len(d["widgets"])


def test_export_and_import_round_trip_exactly(api) -> None:
    d = make(api, "Risk", template="risk")
    document = api.get(f"/api/v1/dashboards/{d['id']}/export").json()
    assert (document["format"], document["version"], document["name"]) == (
        "folio-dashboard",
        1,
        "Risk",
    )
    assert len(document["widgets"]) == 7 and "id" not in document["widgets"][0]
    imported = api.post("/api/v1/dashboards/import", json={"document": document})
    assert imported.status_code == 201, imported.text
    copy = imported.json()
    assert copy["name"] == "Risk 2"  # the name was taken
    assert [(w["type"], w["config"]) for w in copy["widgets"]] == [
        (w["type"], w["config"]) for w in d["widgets"]
    ]
    position = lambda dash: {  # noqa: E731
        bp: sorted(
            (
                dash["widgets"].index(next(w for w in dash["widgets"] if str(w["id"]) == b["i"])),
                b["x"],
                b["y"],
                b["w"],
                b["h"],
            )
            for b in boxes
        )
        for bp, boxes in dash["layouts"].items()
    }
    assert position(copy) == position(d)
    assert (
        api.get(f"/api/v1/dashboards/{copy['id']}/export").json()["widgets"] == document["widgets"]
    )


def test_an_import_that_is_not_ours_or_is_invalid_is_refused(api) -> None:
    def post(document: dict[str, Any]) -> Any:
        return api.post("/api/v1/dashboards/import", json={"document": document})

    assert "not a Folio dashboard" in post({"format": "other"}).json()["detail"]
    assert (
        "version"
        in post({"format": "folio-dashboard", "version": 9, "widgets": []}).json()["detail"]
    )
    bad = post({"format": "folio-dashboard", "version": 1, "widgets": [{"type": "clock"}]})
    assert bad.status_code == 422 and "Widget 1" in bad.json()["detail"]
    wide = post(
        {
            "format": "folio-dashboard", "version": 1, "name": "X",
            "widgets": [{"type": "note", "config": {"text": "hi"}}],
            "layouts": {"lg": [{"i": 0, "x": 10, "y": 0, "w": 6, "h": 2}]},
        }
    )  # fmt: skip
    assert wide.status_code == 422 and "layout in this file" in wide.json()["detail"]
    assert api.get("/api/v1/dashboards").json() == []  # nothing half-imported


# --- the data (FR-DB-03, FR-DB-05) --------------------------------------------------------------


def test_kpi_tiles_match_a_hand_computation(api, book) -> None:
    value = one(api, "kpi", {"metric": "value"})
    assert D(value["value"]) == 1188 and value["kind"] == "eur"
    assert value["sparkline"][-1]["value"] == "1188" and value["as_of"] == AS_OF
    total = one(api, "kpi", {"metric": "total_return"})
    assert D(total["value"]) == 93
    assert abs(D(total["change_ratio"]) - D(93) / D(1098)) < D("1E-20")
    assert D(one(api, "kpi", {"metric": "net_contributions"})["value"]) == 1098
    assert D(one(api, "kpi", {"metric": "period_return", "period": "YTD"})["value"]) == 93
    assert D(one(api, "kpi", {"metric": "income", "period": "YTD"})["value"]) == 3
    assert (
        D(one(api, "kpi", {"metric": "day_change"})["value"]) == 0
    )  # the last close is from 12 Jan
    assert one(api, "kpi", {"metric": "xirr", "period": "YTD"})["value"] is not None
    assert D(one(api, "kpi", {"metric": "twr", "period": "YTD"})["value"]) > 0
    cash = one(api, "kpi", {"metric": "cash"})
    assert cash["empty"] is True and "cash tracking" in cash["reason"]
    drift = one(api, "kpi", {"metric": "largest_drift"})
    assert drift["empty"] is True and "targets" in drift["reason"]


def test_risk_tiles_use_the_last_year(api, book) -> None:
    assert one(api, "kpi", {"metric": "volatility"})["value"] is not None
    assert D(one(api, "kpi", {"metric": "max_drawdown"})["value"]) <= 0
    assert "benchmark" in one(api, "kpi", {"metric": "beta"})["note"]  # none flagged yet


def test_the_dashboards_period_is_followed_unless_the_widget_says_otherwise(api, book) -> None:
    follows = one(api, "kpi", {"metric": "period_return"}, period="1W")
    own = one(api, "kpi", {"metric": "period_return", "period": "YTD"}, period="1W")
    ignores = one(api, "kpi", {"metric": "period_return", "follow_filters": False}, period="1W")
    assert follows["start"] == "2024-01-08" and own["start"] == "2023-12-31"
    assert ignores["start"] == "2023-12-31"  # not following: the default, year to date
    assert D(follows["value"]) != D(own["value"])


def test_a_custom_period_is_a_filter_too(api, book) -> None:
    ok = one(
        api,
        "kpi",
        {"metric": "period_return"},
        period="CUSTOM",
        start="2024-01-11",
        end="2024-01-12",
    )
    assert (ok["start"], ok["end"]) == ("2024-01-11", "2024-01-12")
    assert D(ok["value"]) == 11  # 1177 on the 11th, 1188 on the 12th
    missing = data(api, {"w": ("kpi", {"metric": "period_return"})}, period="CUSTOM")["w"]
    assert "needs both a start and an end" in missing["error"]
    chart = one(api, "value_history", {}, period="CUSTOM", start="2024-01-02", end="2024-01-05")
    assert [p["date"] for p in chart["points"]][-1] == "2024-01-05"


def test_the_account_filter_is_followed_too(api, book) -> None:
    other = api.post("/api/v1/accounts", json={"name": "Other"}).json()["id"]
    mine = one(api, "kpi", {"metric": "value"}, account=book["account"])
    theirs = one(api, "kpi", {"metric": "value"}, account=other)
    assert D(mine["value"]) == 1188 and theirs["empty"] is True
    pinned = one(
        api,
        "kpi",
        {"metric": "value", "scope": {"kind": "account", "id": book["account"]}},
        account=other,
    )
    assert D(pinned["value"]) == 1188  # a widget scoped to an account ignores the filter


def test_a_sleeve_or_instrument_scope_reads_that_part_only(api, book) -> None:
    sleeve = api.post("/api/v1/sleeves", json={"name": "core"}).json()
    api.patch(f"/api/v1/instruments/{book['fund']}", json={"sleeve_id": sleeve["id"]})
    for scope in (
        {"kind": "sleeve", "id": sleeve["id"]},
        {"kind": "instrument", "id": book["fund"]},
    ):
        result = one(api, "kpi", {"metric": "value", "scope": scope})
        assert D(result["value"]) == 1188
    missing = data(api, {"w": ("kpi", {"metric": "value", "scope": {"kind": "sleeve"}})})["w"]
    assert "Choose which sleeve" in missing["error"]


def test_value_history_and_drawdown_charts(api, book) -> None:
    history = one(api, "value_history", {"period": "MAX"})
    assert history["points"][0] == {
        "date": "2024-01-02",
        "value": "1000",
        "net_contributions": "1001",
    }
    assert history["points"][-1]["value"] == "1188" and history["log_scale"] is False
    under = one(api, "drawdown", {"period": "MAX"})
    assert under["points"] and D(under["max_drawdown"]) <= 0
    one_fund = one(
        api, "value_history", {"period": "MAX", "scope": {"kind": "instrument", "id": book["fund"]}}
    )
    assert one_fund["points"][-1]["net_contributions"] == "1098"  # 1521 in, 423 out


def test_allocation_drift_and_holdings(api, book) -> None:
    core = api.post(
        "/api/v1/sleeves", json={"name": "core", "target_pct": "60", "band_pct": "5"}
    ).json()
    api.patch(f"/api/v1/instruments/{book['fund']}", json={"sleeve_id": core["id"]})
    alloc = one(api, "allocation", {"group_by": "sleeve"})
    assert alloc["slices"][0]["key"] == "core" and D(alloc["slices"][0]["drift_pp"]) == D("0.4")
    assert alloc["slices"][0]["outside_band"] is True
    through = one(api, "allocation", {"look_through": True, "group_by": "company"})
    assert through["look_through"] is True and through["unopened"] == ["F fund"]  # no holdings yet
    refused = data(api, {"w": ("allocation", {"look_through": True})})["w"]  # asset_class: no
    assert "company, sector, country or currency" in refused["error"]
    bars = one(api, "drift_bars")["bars"]
    assert (bars[0]["key"], D(bars[0]["band"])) == ("core", D("0.05"))
    table = one(api, "holdings_table")
    [row] = table["rows"]
    assert (row["name"], D(row["quantity"]), D(row["value"])) == ("F fund", 11, 1188)
    assert row["sleeve"] == "core" and D(table["totals"]["value"]) == 1188


def test_returns_widgets(api, book) -> None:
    heat = one(api, "returns_heatmap", {"period": "YTD"})
    assert [c["name"] for c in heat["cells"]] == ["F fund"] and D(heat["cells"][0]["pnl_eur"]) == 93
    monthly = one(api, "monthly_returns")
    assert monthly["years"][0]["year"] == 2024 and "1" in monthly["years"][0]["months"]
    bridge = one(api, "return_bridge", {"period": "YTD"})
    steps = {s["label"]: D(s["amount_eur"]) for s in bridge["steps"]}
    assert steps["start"] == 0 and steps["contributions"] == 1098
    assert steps["F fund"] == 90 and steps["end"] == 1188  # the 3 of income is not in the value
    attribution = one(api, "attribution", {"period": "YTD"})
    assert D(attribution["portfolio_pnl_eur"]) == 93  # 90 of price gain and 3 of income
    assert sum(D(r["pnl_eur"]) for r in attribution["rows"]) == D(attribution["portfolio_pnl_eur"])
    assert attribution["rows"][0]["name"] == "F fund" and D(attribution["rows"][0]["pnl_eur"]) == 93
    income = one(api, "income", {"period": "YTD"})
    assert income["months"] == [{"month": "2024-01", "dividends": "3", "interest": "0"}]
    assert D(income["total_eur"]) == 3
    corr = one(api, "correlation_matrix")
    assert corr["empty"] is True and "at least two" in corr["reason"]


def test_price_chart_with_trades_and_averages(api, book, db) -> None:
    chart = one(
        api,
        "price_chart",
        {"instrument_id": book["fund"], "period": "MAX", "overlays": ["trades", "ma50"]},
    )
    assert chart["name"] == "F fund" and chart["currency"] == "EUR"
    assert chart["points"][-1]["close"] == "108"  # the close of 12 Jan
    assert [(t["date"], t["type"], t["quantity"]) for t in chart["trades"]] == [
        ("2024-01-02", "buy", "10"), ("2024-01-08", "buy", "5"), ("2024-01-11", "sell", "4"),
    ]  # fmt: skip
    assert chart["ma50"] == []  # not enough days for a 50-day average yet
    nothing = one(api, "price_chart", {})
    assert nothing["empty"] is True and "Choose an instrument" in nothing["reason"]


def test_a_fifty_day_average_is_the_mean_of_fifty_closes(api, db) -> None:
    fund, listing = make_listing(db, ticker="F")
    for i in range(60):
        day = date.fromordinal(date(2023, 10, 2).toordinal() + i)
        db.add(PriceBar(listing_id=listing.id, date=day, close=D(100 + i), source="x"))
    db.commit()
    account = api.post("/api/v1/accounts", json={"name": "A"}).json()["id"]
    tx(
        api,
        account_id=account,
        instrument_id=fund.id,
        type="buy",
        trade_date="2023-10-02",
        quantity="1",
        price="100",
    )
    chart = one(
        api, "price_chart", {"instrument_id": fund.id, "period": "MAX", "overlays": ["ma50"]}
    )
    first = chart["ma50"][0]
    assert first["date"] == "2023-11-20"  # the 50th close
    assert D(first["value"]) == sum(D(100 + i) for i in range(50)) / 50  # 124.5


def test_performance_comparison_lists_the_portfolio_and_flagged_benchmarks(api, book, db) -> None:
    bench, listing = make_listing(db, ticker="B", isin=None)
    for bar in bars_for("XETR", date(2024, 1, 1), date(2024, 1, 12), first_close=50):
        db.add(PriceBar(listing_id=listing.id, date=bar.date, close=bar.close, source="x"))
    db.commit()
    assert one(api, "performance_comparison", {"period": "YTD"})["suggest_benchmark"] is True
    api.patch(f"/api/v1/instruments/{bench.id}", json={"is_benchmark": True})
    out = one(api, "performance_comparison", {"period": "YTD"})
    assert out["suggest_benchmark"] is False  # one is chosen now
    assert [s["key"] for s in out["series"]] == ["portfolio", f"benchmark:{bench.id}"]
    assert D(out["series"][1]["points"][0]["value"]) == 100


def test_the_note_widget_keeps_its_text_and_quiet_feeds_say_so(api, book) -> None:
    assert one(api, "note", {"text": "# Plan"}) == {"text": "# Plan"}
    for kind in ("news_feed", "signals"):  # nothing linked and nothing waiting yet
        out = one(api, kind)
        assert out["empty"] is True and out["reason"]


def test_one_failing_widget_does_not_fail_the_others(api, book) -> None:
    results = data(
        api,
        {
            "good": ("kpi", {"metric": "value"}),
            "badscope": ("kpi", {"scope": {"kind": "instrument"}}),
            "badoption": ("kpi", {"metric": "fun"}),
            "badtype": ("clock", {}),
        },
    )
    assert results["good"]["error"] is None
    assert "Choose which" in results["badscope"]["error"]
    assert "not valid" in results["badoption"]["error"]
    assert "Unknown widget type" in results["badtype"]["error"]


def test_widget_data_input_is_bounded(api) -> None:
    assert api.post("/api/v1/widgets/data", json={"requests": []}).status_code == 422
    many = [{"key": str(i), "type": "note"} for i in range(61)]
    assert api.post("/api/v1/widgets/data", json={"requests": many}).status_code == 422


# --- live updates (FR-DB-04) --------------------------------------------------------------------


def stream(api: TestClient, path: str = "/api/v1/events", **headers: str) -> str:
    with api.stream("GET", path, headers=headers) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        return "".join(r.iter_text())


@pytest.fixture
def fast_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(events_router, "POLL_SECONDS", 0.05)


def test_events_are_streamed_in_order_with_their_ids(api, db, fast_polling) -> None:
    first = publish_event(db, "price_update", {"mic": "XETR"})
    second = publish_event(db, "job_status", {"job": "eod", "status": "ok"})
    db.commit()
    text = stream(api, "/api/v1/events?last_event_id=0&seconds=0.3")
    assert f'id: {first.id}\nevent: price_update\ndata: {{"mic": "XETR"}}' in text
    assert f"id: {second.id}\nevent: job_status" in text
    assert text.index("price_update") < text.index("job_status")
    assert text.startswith("retry: 3000")


def test_a_reconnecting_browser_resumes_after_the_last_event_it_saw(api, db, fast_polling) -> None:
    a = publish_event(db, "price_update")
    b = publish_event(db, "job_status")
    db.commit()
    text = stream(api, "/api/v1/events?seconds=0.3", **{"Last-Event-ID": str(a.id)})
    assert f"id: {b.id}" in text and f"id: {a.id}\n" not in text


def test_a_new_stream_only_sees_what_happens_after_it_opens(api, db, fast_polling) -> None:
    publish_event(db, "price_update", {"old": True})
    db.commit()
    text = stream(api, "/api/v1/events?seconds=0.2")
    assert "old" not in text


def test_events_need_a_login(client: TestClient) -> None:
    assert client.get("/api/v1/events?seconds=1").status_code == 401
    for path in ("/api/v1/dashboards", "/api/v1/dashboards/default", "/api/v1/dashboard-templates"):
        assert client.get(path).status_code == 401
    assert client.post("/api/v1/widgets/data", json={"requests": []}).status_code == 401


def test_a_new_close_stored_by_the_worker_produces_an_event(settings, api, db) -> None:  # type: ignore[no-untyped-def]
    """FR-DB-04: the job that stores a close tells the browser, which refreshes without a reload."""
    from folio.jobs.market import eod_job

    held, listing = make_listing(db, ticker="W")
    db.commit()
    day = date(2024, 1, 9)
    provider = FakeProvider(bars={listing.id: bars_for("XETR", date(2024, 1, 1), day)})
    result = eod_job(make_ctx(settings, [provider]), "XETR", day=day)
    assert result.status == "ok"
    db.expire_all()
    kinds = [e.type for e in db.scalars(select(AppEvent).order_by(AppEvent.id))]
    assert kinds == ["price_update", "job_status"]


def test_a_price_entered_by_hand_tells_the_browser(api, db) -> None:
    """The web process publishes too, so a dashboard open in another tab updates."""
    instrument, _ = make_listing(db, ticker="M", isin=None, manual=True)
    db.commit()
    before = db.scalar(select(func.max(AppEvent.id))) or 0
    r = api.post(
        f"/api/v1/instruments/{instrument.id}/prices", json={"date": "2024-01-09", "close": "12.5"}
    )
    assert r.status_code == 201, r.text
    db.expire_all()
    new = db.scalars(select(AppEvent).where(AppEvent.id > before)).all()
    assert [e.type for e in new] == ["price_update"] and new[0].payload["source"] == "manual"


def test_a_portfolio_without_any_price_says_so_in_the_allocation(api, db) -> None:
    fund, _ = make_listing(db, ticker="U")
    db.commit()
    account = api.post("/api/v1/accounts", json={"name": "A"}).json()["id"]
    tx(
        api,
        account_id=account,
        instrument_id=fund.id,
        type="buy",
        trade_date="2024-01-02",
        quantity="1",
        price="10",
    )
    out = one(api, "allocation")
    assert out["empty"] is True and out["unvalued"] == 1
    assert "None of your holdings has a price yet" in out["reason"]
