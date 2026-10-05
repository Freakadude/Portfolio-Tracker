"""The System page: version, disk use, agent cost and failing jobs (FR-SY-10)."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from folio.config import Settings
from folio.jobs.market import backfill_job
from tests.conftest import PASSWORD, USERNAME
from tests.marketdata_helpers import make_ctx


@pytest.fixture
def api(client: TestClient, owner: None) -> TestClient:
    client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return client


def test_info_shows_version_disk_and_the_agent_row(api: TestClient) -> None:
    info = api.get("/api/v1/system/info").json()
    assert info["version"] == "0.1.0" and info["build"] is None
    assert info["disk"]["database_bytes"] > 0  # the test database file
    assert (
        info["disk"]["free_bytes"] > 0 and info["disk"]["total_bytes"] >= info["disk"]["free_bytes"]
    )
    assert (info["disk"]["backups"], info["disk"]["backups_bytes"]) == (0, 0)
    assert info["agent"]["runs_this_month"] == 0 and info["agent"]["budget_eur"] == "5"  # Q6
    assert "Phase 4" in info["agent"]["note"]


def test_a_failing_job_is_visible_after_one_run(api: TestClient, settings: Settings) -> None:
    assert api.get("/api/v1/system/info").json()["failed_jobs_24h"] == 0
    result = backfill_job(make_ctx(settings, [], now=datetime.now(UTC)), 99999)
    assert result.status == "failed"
    (run,) = api.get("/api/v1/system/jobs").json()["runs"]
    assert (run["job"], run["status"]) == ("backfill", "failed") and run[
        "duration_seconds"
    ] is not None
    assert api.get("/api/v1/system/info").json()["failed_jobs_24h"] == 1


def test_the_build_comes_from_the_image(make_client, owner: None, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    settings.version = "abc1234"
    api = make_client()
    api.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    assert api.get("/api/v1/system/info").json()["build"] == "abc1234"
