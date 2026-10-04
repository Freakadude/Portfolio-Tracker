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
