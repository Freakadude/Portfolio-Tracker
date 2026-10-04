import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import AuditLog
from folio.settings_schema import SECTIONS
from tests.conftest import PASSWORD, USERNAME

KEY = "eodhd-SENTINEL-key-0123456789"


@pytest.fixture
def signed_in(client: TestClient, owner: None) -> TestClient:
    client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return client


def test_settings_require_login(client: TestClient) -> None:
    assert client.get("/api/v1/settings/general").status_code == 401


@pytest.mark.parametrize("section", sorted(SECTIONS))
def test_every_section_reads_and_round_trips(signed_in: TestClient, section: str) -> None:
    current = signed_in.get(f"/api/v1/settings/{section}")
    assert current.status_code == 200
    body = {k: v for k, v in current.json().items() if k not in SECTIONS[section].SECRETS}
    assert signed_in.put(f"/api/v1/settings/{section}", json=body).status_code == 200
    assert signed_in.get(f"/api/v1/settings/{section}").json() == current.json()


def test_defaults_match_the_spec_and_owner_decisions(signed_in: TestClient) -> None:
    agent = signed_in.get("/api/v1/settings/agent").json()
    assert agent["monthly_budget_eur"] == "5"  # Q6
    assert agent["privacy_mode"] is True
    assert agent["models"]["weekly_review"] == "claude-opus-5-5"
    notifications = signed_in.get("/api/v1/settings/notifications").json()
    assert notifications["channel"] == "home_assistant"  # Q5
    assert (notifications["quiet_hours_start"], notifications["quiet_hours_end"]) == (
        "22:00",
        "07:30",
    )
    assert notifications["daily_push_cap"] == 5
    retention = signed_in.get("/api/v1/settings/retention").json()
    assert (retention["quotes_days"], retention["agent_runs_days"], retention["news_days"]) == (
        7,
        90,
        365,
    )
    general = signed_in.get("/api/v1/settings/general").json()
    assert general["timezone"] == "Europe/Amsterdam"
    assert (
        signed_in.get("/api/v1/settings/providers").json()["providers"]["yfinance"]["enabled"]
        is False
    )


def test_validation_errors_are_problem_json_in_plain_language(signed_in: TestClient) -> None:
    r = signed_in.put("/api/v1/settings/general", json={"timezone": "Mars/Base"})
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    assert "Unknown timezone" in r.json()["errors"][0]["message"]
    bad = signed_in.put("/api/v1/settings/notifications", json={"quiet_hours_start": "25:99"})
    assert bad.status_code == 422
    assert signed_in.get("/api/v1/settings/nope").status_code == 404


def test_secret_is_masked_and_survives_unrelated_saves(signed_in: TestClient) -> None:
    saved = signed_in.put("/api/v1/settings/providers", json={"eodhd_api_key": KEY}).json()
    assert saved["eodhd_api_key"].endswith(KEY[-4:]) and KEY not in str(saved)
    # null leaves it alone; echoing the masked value back must not overwrite it either
    signed_in.put("/api/v1/settings/providers", json={"eodhd_api_key": None})
    signed_in.put("/api/v1/settings/providers", json={"eodhd_api_key": saved["eodhd_api_key"]})
    assert (
        signed_in.get("/api/v1/settings/providers").json()["eodhd_api_key"]
        == saved["eodhd_api_key"]
    )
    cleared = signed_in.put("/api/v1/settings/providers", json={"eodhd_api_key": ""}).json()
    assert cleared["eodhd_api_key"] is None


def test_changes_are_audited_without_leaking_secrets(
    signed_in: TestClient, settings: Settings
) -> None:
    signed_in.put(
        "/api/v1/settings/agent", json={"monthly_budget_eur": "7.50", "anthropic_api_key": KEY}
    )
    with make_session_factory(make_engine(settings.db_url))() as db:
        rows = list(db.scalars(select(AuditLog).where(AuditLog.entity == "setting")))
    assert len(rows) == 1
    diff = rows[0].diff
    assert diff["monthly_budget_eur"] == {"old": "5", "new": "7.50"}
    assert diff["anthropic_api_key"]["old"] is None
    assert diff["anthropic_api_key"]["new"].endswith(KEY[-4:])
    assert KEY not in str(diff)


def test_key_saved_through_the_api_is_never_stored_in_plaintext(
    signed_in: TestClient, settings: Settings
) -> None:
    from pathlib import Path

    signed_in.put("/api/v1/settings/providers", json={"eodhd_api_key": KEY})
    signed_in.put("/api/v1/settings/agent", json={"anthropic_api_key": KEY + "-anthropic"})
    db_path = Path(settings.db_url.removeprefix("sqlite:///"))
    blobs = [p.read_bytes() for p in db_path.parent.glob(f"{db_path.name}*")]
    assert blobs and not any(KEY.encode() in b for b in blobs)
