"""Strategies through the API: versions, diffs, active and shadow, sleeves that follow the active
strategy (FR-ST-01, FR-ST-02)."""

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import AuditLog
from folio.db.models_strategy import StrategyVersion
from tests.conftest import PASSWORD, USERNAME

D = Decimal

YAML = """\
strategy:
  name: Core
  principles: [Direct new money first.]
  sleeves:
    - { id: equity, members: [IE00B5BMR087], target_pct: 70, soft_band_pp: 5, hard_band_pp: 10 }
    - { id: gold, members: [], target_pct: 30, soft_band_pp: 5 }
  rules:
    - { id: drift, type: drift_band }
"""


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


@pytest.fixture
def api(client: TestClient, owner: None) -> TestClient:
    client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return client


def create(api: TestClient, text: str = YAML, **extra: Any) -> dict[str, Any]:
    r = api.post("/api/v1/strategies", json={"yaml": text, **extra})
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def test_invalid_yaml_is_refused_with_the_line(api: TestClient) -> None:
    r = api.post(
        "/api/v1/strategies", json={"yaml": YAML.replace("target_pct: 70", "target_pct: x")}
    )
    assert r.status_code == 422
    body = r.json()
    assert body["detail"].startswith("line 5:")
    assert body["problems"][0] == {
        "line": 5,
        "path": "strategy.sleeves[0].target_pct",
        "message": body["problems"][0]["message"],
    }
    assert api.get("/api/v1/strategies").json() == []  # nothing saved


def test_check_validates_without_saving_and_returns_both_forms(api: TestClient) -> None:
    ok = api.post("/api/v1/strategies/check", json={"yaml": YAML}).json()
    assert ok["ok"] is True and ok["definition"]["sleeves"][0]["target_pct"] == "70"
    back = api.post("/api/v1/strategies/check", json={"definition": ok["definition"]}).json()
    assert back["ok"] is True and "target_pct: 70" in back["yaml"]
    bad = api.post("/api/v1/strategies/check", json={"yaml": "strategy: [1"}).json()
    assert bad["ok"] is False and bad["problems"][0]["line"] == 1
    both = api.post("/api/v1/strategies/check", json={"yaml": YAML, "definition": {}})
    assert both.status_code == 422


def test_every_save_adds_an_immutable_version_and_versions_can_be_compared(
    api: TestClient, db
) -> None:  # type: ignore[no-untyped-def]
    s = create(api, note="first")
    assert (s["name"], s["mode"], s["current"]["version"]) == ("Core", "off", 1)
    first_yaml = s["current"]["yaml"]
    assert first_yaml == YAML  # kept as written

    changed = YAML.replace("target_pct: 30", "target_pct: 25").replace(
        "name: Core", "name: Core v2"
    )
    r = api.post(
        f"/api/v1/strategies/{s['id']}/versions", json={"yaml": changed, "note": "less gold"}
    )
    assert r.status_code == 201
    after = r.json()
    assert after["name"] == "Core v2" and [v["version"] for v in after["versions"]] == [2, 1]
    assert api.get(f"/api/v1/strategies/{s['id']}/versions/1").json()["yaml"] == first_yaml

    diff = api.get(f"/api/v1/strategies/{s['id']}/diff", params={"old": 1, "new": 2}).json()
    changed_rows = [r for r in diff["rows"] if r["kind"] != "same"]
    assert [(r["old_line"], r["new_line"]) for r in changed_rows] == [(2, 2), (6, 6)]
    assert "25" in changed_rows[1]["new_text"] and "30" in changed_rows[1]["old_text"]

    # the form view saves canonical YAML
    form = api.post(
        f"/api/v1/strategies/{s['id']}/versions",
        json={"definition": after["current"]["definition"] | {"principles": ["Only new money."]}},
    ).json()
    assert form["current"]["version"] == 3 and "Only new money." in form["current"]["yaml"]
    assert len(db.scalars(select(StrategyVersion)).all()) == 3
    assert api.get(f"/api/v1/strategies/{s['id']}/versions/9").status_code == 404


def test_one_active_strategy_the_previous_one_becomes_a_shadow(api: TestClient, db) -> None:  # type: ignore[no-untyped-def]
    a = create(api)
    b = create(api, YAML.replace("name: Core", "name: Challenger"))
    api.post(f"/api/v1/strategies/{a['id']}/mode", json={"mode": "active"})
    modes = api.post(f"/api/v1/strategies/{b['id']}/mode", json={"mode": "active"}).json()
    assert {m["name"]: m["mode"] for m in modes} == {"Core": "shadow", "Challenger": "active"}
    audit = db.scalars(
        select(AuditLog).where(AuditLog.entity == "strategy", AuditLog.action == "mode")
    ).all()
    assert len(audit) == 3  # a: off->active, a: active->shadow, b: off->active
    assert api.post(f"/api/v1/strategies/{a['id']}/mode", json={"mode": "on"}).status_code == 422


def test_sleeves_follow_the_active_strategy(api: TestClient) -> None:
    fund = api.post(
        "/api/v1/instruments",
        json={
            "name": "S&P fund",
            "asset_class": "ETF",
            "manual": True,
            "currency": "EUR",
            "isin": "IE00B5BMR087",
        },
    ).json()
    old = api.post("/api/v1/sleeves", json={"name": "legacy", "target_pct": "50"}).json()
    s = create(api)
    api.post(f"/api/v1/strategies/{s['id']}/mode", json={"mode": "active"})

    sleeves = {x["name"]: x for x in api.get("/api/v1/sleeves").json()}
    assert (D(sleeves["equity"]["target_pct"]), D(sleeves["equity"]["band_pct"])) == (70, 5)
    assert sleeves["gold"]["target_pct"] is not None and sleeves["legacy"]["target_pct"] is None
    assert sleeves["equity"]["managed_by"] == "Core" and sleeves["equity"]["instrument_count"] == 1
    assert (
        api.get(f"/api/v1/instruments/{fund['id']}").json()["sleeve_id"] == sleeves["equity"]["id"]
    )

    refused = api.patch(f"/api/v1/sleeves/{old['id']}", json={"target_pct": "10"})
    assert refused.status_code == 409 and "active strategy Core" in refused.json()["detail"]
    assert api.patch(f"/api/v1/sleeves/{old['id']}", json={"name": "old"}).status_code == 200

    # a new version of the active strategy updates the targets at once
    api.post(
        f"/api/v1/strategies/{s['id']}/versions",
        json={"yaml": YAML.replace("target_pct: 70", "target_pct: 65")},
    )
    equity = next(x for x in api.get("/api/v1/sleeves").json() if x["name"] == "equity")
    assert D(equity["target_pct"]) == 65

    # switched off, the sleeves are yours to edit again
    api.post(f"/api/v1/strategies/{s['id']}/mode", json={"mode": "off"})
    assert api.patch(f"/api/v1/sleeves/{old['id']}", json={"target_pct": "10"}).status_code == 200
    assert api.get("/api/v1/sleeves").json()[0]["managed_by"] is None


def test_the_starter_uses_your_sleeves_and_is_valid(api: TestClient) -> None:
    api.post("/api/v1/sleeves", json={"name": "us_equity"})
    starter = api.get("/api/v1/strategies/starter").json()
    assert [x["id"] for x in starter["definition"]["sleeves"]] == ["us_equity"]
    assert all(x["target_pct"] is None for x in starter["definition"]["sleeves"])
    assert api.post("/api/v1/strategies", json={"yaml": starter["yaml"]}).status_code == 201


def test_a_deleted_strategy_is_gone_and_releases_the_sleeves(api: TestClient) -> None:
    s = create(api)
    api.post(f"/api/v1/strategies/{s['id']}/mode", json={"mode": "active"})
    assert api.delete(f"/api/v1/strategies/{s['id']}").status_code == 204
    assert api.get(f"/api/v1/strategies/{s['id']}").status_code == 404
    assert api.get("/api/v1/sleeves").json()[0]["managed_by"] is None


def test_the_json_schema_is_served_for_the_form(api: TestClient) -> None:
    schema = api.get("/api/v1/strategies/schema").json()
    assert "strategy" in schema["properties"] and "StrategyDef" in schema["$defs"]


# The definition the guided setup sends with every option on (web/src/strategies/wizardLogic.ts,
# buildDefinition): kept here so the front end's shape and the schema cannot drift apart.
WIZARD_DEFINITION: dict[str, Any] = {
    "name": "My plan",
    "base_currency": "EUR",
    "principles": ["Rebalance by directing new contributions to underweight sleeves first."],
    "prefer_buys": True,
    "macro_series": {},
    "sleeves": [
        {
            "id": "World",
            "members": ["IE00B5BMR087"],
            "target_pct": "70",
            "soft_band_pp": "3",
            "hard_band_pp": "6",
            "trim_threshold_pct": "80",
        },
        {
            "id": "Bonds",
            "members": [],
            "target_pct": "30",
            "soft_band_pp": "3",
            "hard_band_pp": "6",
            "trim_threshold_pct": "40",
        },
    ],
    "risk_limits": {"max_single_company_lookthrough_pct": "10", "max_thematic_total_pct": None},
    "rules": [
        {
            "id": "drift",
            "type": "drift_band",
            "severity": "medium",
            "cooldown_days": 7,
            "applies_to": "all",
        },
        {
            "id": "trims",
            "type": "trim_threshold",
            "severity": "high",
            "cooldown_days": 14,
            "applies_to": "all",
        },
        {
            "id": "drawdown",
            "type": "drawdown",
            "severity": "medium",
            "cooldown_days": 14,
            "scope": "position",
            "threshold_pct": "20",
        },
        {"id": "stale", "type": "stale_data", "severity": "high", "cooldown_days": 1},
        {
            "id": "concentration",
            "type": "concentration_limit",
            "severity": "medium",
            "cooldown_days": 7,
            "dimension": "company",
            "limit_pct": "10",
        },
        {
            "id": "contribution",
            "type": "contribution_due",
            "severity": "low",
            "cooldown_days": 7,
            "days_before": 3,
        },
    ],
    "theses": [],
    "contribution_plan": {"amount_eur": "250", "cadence": "monthly", "next_date": "2026-11-01"},
}


def test_a_definition_shaped_like_the_guided_setup_is_accepted_and_sets_the_targets(
    api: TestClient,
) -> None:
    created = api.post(
        "/api/v1/strategies", json={"definition": WIZARD_DEFINITION, "note": "guided setup"}
    )
    assert created.status_code == 201, created.text
    assert api.post(f"/api/v1/strategies/{created.json()['id']}/mode", json={"mode": "active"})
    sleeves = {x["name"]: x for x in api.get("/api/v1/sleeves").json()}
    assert (D(sleeves["World"]["target_pct"]), D(sleeves["World"]["band_pct"])) == (70, 3)
    assert D(sleeves["Bonds"]["target_pct"]) == 30
