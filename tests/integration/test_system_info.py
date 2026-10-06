"""The System page: version, disk use, agent cost and failing jobs (FR-SY-10)."""

from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError

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
    assert "Add your Anthropic API key" in info["agent"]["note"]  # nothing is spent without one


def test_info_works_when_the_package_metadata_is_missing(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The container image installs the dependencies only, so there is no metadata for folio and
    the System page showed "Internal Server Error"."""

    def missing(_name: str) -> str:
        raise PackageNotFoundError("folio")

    monkeypatch.setattr("folio.api.routers.system.package_version", missing)
    response = api.get("/api/v1/system/info")
    assert response.status_code == 200
    assert response.json()["version"] == "0.1.0"  # read from pyproject.toml


def test_an_unexpected_error_names_its_kind_and_points_to_the_log(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom() -> str:
        raise ZeroDivisionError("secret 1234.56 EUR")

    monkeypatch.setattr("folio.api.routers.system._folio_version", boom)
    quiet = TestClient(api.app, raise_server_exceptions=False, cookies=api.cookies)
    response = quiet.get("/api/v1/system/info")
    assert response.status_code == 500
    body = response.json()
    assert body["title"] == "Unexpected error" and "ZeroDivisionError" in body["detail"]
    assert "1234.56" not in response.text  # the message may hold data and stays in the log


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
