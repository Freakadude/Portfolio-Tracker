from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.mark.parametrize("service", ["web", "worker"])
def test_app_services_are_hardened(compose: dict[str, Any], service: str) -> None:
    svc = compose["services"][service]
    assert svc["read_only"] is True
    assert svc["user"] == "10001:10001"
    assert "no-new-privileges:true" in svc["security_opt"]
    assert "/tmp" in svc["tmpfs"]
    assert svc["volumes"] == ["folio-data:/data"]


def test_ports_bind_to_the_lan_interface_only(compose: dict[str, Any]) -> None:
    for service in ("web", "ntfy"):
        for port in compose["services"][service]["ports"]:
            assert port.startswith("${FOLIO_LAN_IP"), f"{service} port {port} is not LAN-bound"
    assert "ports" not in compose["services"]["worker"]  # the worker listens on nothing


def test_folio_is_reachable_on_port_8555(compose: dict[str, Any]) -> None:
    (port,) = compose["services"]["web"]["ports"]
    assert port == "${FOLIO_LAN_IP:?set FOLIO_LAN_IP}:${FOLIO_WEB_PORT:-8555}:8080"
    # the app still listens on 8080 inside the container, which the health check uses
    assert "http://localhost:8080/healthz" in compose["services"]["web"]["healthcheck"]["test"]


def test_worker_waits_for_web_migrations(compose: dict[str, Any]) -> None:
    assert compose["services"]["worker"]["depends_on"]["web"]["condition"] == "service_healthy"
    assert "healthcheck" in compose["services"]["web"]


def test_ntfy_is_optional(compose: dict[str, Any]) -> None:
    assert compose["services"]["ntfy"]["profiles"] == ["ntfy"]


def test_dockerfile_runs_as_non_root_with_pinned_bases() -> None:
    text = (ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
    assert "USER 10001:10001" in text
    assert "FROM python:3.12-slim" in text and "FROM node:24-slim" in text
    assert ":latest" not in text


def test_env_example_lists_every_documented_variable() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for name in (
        "FOLIO_SECRET_KEY",
        "FOLIO_LAN_IP",
        "FOLIO_DB_URL",
        "FOLIO_BASE_URL",
        "FOLIO_TZ",
        "FOLIO_LOG_LEVEL",
        "FOLIO_BACKUP_DIR",
        "FOLIO_EXTRA_BACKUP_DIR",
    ):
        assert name in text


def test_the_stack_pulls_the_published_image_and_needs_no_env_file(
    compose: dict[str, Any],
) -> None:
    for service in ("web", "worker"):
        svc = compose["services"][service]
        assert svc["image"].startswith("${FOLIO_IMAGE:-ghcr.io/freakadude/portfolio-tracker:")
        assert "build" not in svc  # building is the optional override
        assert "env_file" not in svc  # a Portainer stack has no .env next to it
        assert svc["pull_policy"] == "always"
    env = compose["services"]["web"]["environment"]
    assert env["FOLIO_SECRET_KEY"].startswith("${FOLIO_SECRET_KEY:?")  # refuses to start without
    assert compose["services"]["worker"]["environment"] == env


def test_ci_publishes_only_a_green_main_with_the_workflows_own_token() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    job = workflow["jobs"]["publish"]
    assert job["if"] == "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    assert set(job["needs"]) >= {"python", "web", "image", "secrets"}
    assert job["permissions"] == {"contents": "read", "packages": "write"}
    assert workflow["permissions"] == {"contents": "read"}  # nothing else can publish
    text = yaml.safe_dump(job)
    assert "secrets.GITHUB_TOKEN" in text
    assert "secrets.GITHUB_TOKEN" not in yaml.safe_dump(workflow["jobs"]["image"])
