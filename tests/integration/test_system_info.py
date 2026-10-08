"""The System page: version, disk use, agent cost and failing jobs (FR-SY-10)."""

from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError

import pytest
from fastapi.testclient import TestClient

from folio.config import Settings
from folio.jobs.market import backfill_job
from tests.conftest import FAKE_API_KEY, PASSWORD, USERNAME
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


def test_the_diagnostics_file_shows_failures_and_nothing_private(
    api: TestClient, settings: Settings
) -> None:
    """FR-SY-10: a file to attach to a bug report; no keys, holdings or amounts in it."""
    import logging
    import re

    from folio.logging import configure_logging

    api.put("/api/v1/settings/providers", json={"eodhd_api_key": FAKE_API_KEY})
    made = api.post(
        "/api/v1/instruments",
        json={
            "name": "Secret Holdings Fund",
            "asset_class": "BOND",
            "manual": True,
            "currency": "EUR",
        },
    )
    assert made.status_code == 201, made.text
    backfill_job(make_ctx(settings, [], now=datetime.now(UTC)), 99999)  # a failing job
    configure_logging()
    logging.getLogger("folio.test").warning("the key sk-ant-abcdefghijkl1234 was rejected")

    response = api.get("/api/v1/system/diagnostics")
    assert response.status_code == 200
    assert re.fullmatch(
        r'attachment; filename="folio-diagnostics-\d{8}-\d{6}\.json"',
        response.headers["content-disposition"],
    )
    report = response.json()
    assert report["database"]["migration_at_head"] is True
    assert report["database"]["rows"]["instruments"] == 1  # counted, never named
    assert report["failed_jobs_24h"] == 1
    assert [r["job"] for r in report["recent_job_runs"]] == ["backfill"]
    assert report["configuration"]["secrets_with_a_value"] == ["providers.eodhd_api_key"]
    problems = report["recent_warnings_and_errors_from_the_web_server"]
    assert any("was rejected" in line for line in problems)  # other tests log warnings too
    assert not any("sk-ant-abcdefghijkl1234" in line for line in problems)
    for private in (FAKE_API_KEY, "Secret Holdings Fund", PASSWORD):
        assert private not in response.text


def test_the_diagnostics_file_needs_a_login(client: TestClient) -> None:
    assert client.get("/api/v1/system/diagnostics").status_code == 401


# --- how long the containers have been running, and which commit (FR-SY-10) ------------------


def test_the_web_container_reports_its_commit_and_how_long_it_has_run(api: TestClient) -> None:
    web = api.get("/api/v1/system/info").json()["web"]
    assert web["build"] is None  # the test settings carry no build (the image sets it)
    assert 0 <= web["uptime_seconds"] < 120
    started = datetime.fromisoformat(web["started_at"])
    assert (datetime.now(UTC) - started).total_seconds() < 120


def test_the_worker_is_unknown_until_it_reports_then_alive_or_not(
    api: TestClient, settings: Settings
) -> None:
    from datetime import timedelta

    from folio.jobs import heartbeat

    assert api.get("/api/v1/system/info").json()["worker"] is None  # it has not written yet
    now = datetime.now(UTC)
    heartbeat.write(settings, now - timedelta(hours=3, minutes=5), now - timedelta(seconds=20))
    worker = api.get("/api/v1/system/info").json()["worker"]
    assert worker["alive"] is True and 10 <= worker["seen_seconds_ago"] < 120
    assert 3 * 3600 + 5 * 60 <= worker["uptime_seconds"] < 3 * 3600 + 5 * 60 + 120
    heartbeat.write(settings, now - timedelta(hours=3), now - timedelta(minutes=10))
    stale = api.get("/api/v1/system/info").json()["worker"]
    assert stale["alive"] is False and stale["seen_seconds_ago"] >= 600


def test_the_worker_status_file_is_written_atomically_and_a_bad_one_is_ignored(
    settings: Settings,
) -> None:
    from folio.jobs import heartbeat

    when = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)
    heartbeat.write(settings, when, when)
    status = heartbeat.read(settings)
    assert status is not None and status.started_at == when and status.build == settings.version
    path = heartbeat._path(settings)  # noqa: SLF001 - the file the web container reads
    assert path is not None and not path.with_suffix(".tmp").exists()
    path.write_text("not json", encoding="utf-8")
    assert heartbeat.read(settings) is None
