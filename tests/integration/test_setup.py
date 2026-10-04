from fastapi.testclient import TestClient
from sqlalchemy import select

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import Account, AuditLog

PASSWORD = "a long enough passphrase"


def _status(client: TestClient) -> dict:  # type: ignore[type-arg]
    return client.get("/api/v1/setup/status").json()


def test_full_wizard_flow(client: TestClient, settings: Settings) -> None:
    assert _status(client) == {
        "needs_owner": True,
        "authenticated": False,
        "has_account": False,
        "setup_complete": False,
    }

    r = client.post("/api/v1/setup/owner", json={"username": "Owner", "password": PASSWORD})
    assert r.status_code == 201 and r.json() == {"username": "owner"}
    assert client.get("/api/v1/auth/me").json() == {"username": "owner"}  # signed in already

    prefs = client.put(
        "/api/v1/settings/general", json={"timezone": "Europe/Amsterdam", "number_format": "us"}
    )
    assert prefs.status_code == 200 and prefs.json()["number_format"] == "us"

    acc = client.post(
        "/api/v1/setup/account",
        json={"name": "Degiro", "broker": "Degiro", "cost_basis_method": "FIFO"},
    )
    assert acc.status_code == 201 and acc.json()["name"] == "Degiro"

    # provider keys and the notification channel are skippable; finishing works without them
    assert client.post("/api/v1/setup/complete").status_code == 204
    assert _status(client) == {
        "needs_owner": False,
        "authenticated": True,
        "has_account": True,
        "setup_complete": True,
    }

    with make_session_factory(make_engine(settings.db_url))() as db:
        assert db.scalar(select(Account)).name == "Degiro"  # type: ignore[union-attr]
        actions = {(a.entity, a.action) for a in db.scalars(select(AuditLog))}
    assert {("user", "create"), ("account", "create"), ("setup", "complete")} <= actions


def test_owner_can_only_be_created_once(client: TestClient) -> None:
    body = {"username": "owner", "password": PASSWORD}
    assert client.post("/api/v1/setup/owner", json=body).status_code == 201
    second = client.post("/api/v1/setup/owner", json={"username": "x", "password": PASSWORD})
    assert second.status_code == 409


def test_weak_password_is_explained_in_plain_language(client: TestClient) -> None:
    r = client.post("/api/v1/setup/owner", json={"username": "owner", "password": "short"})
    assert r.status_code == 422
    assert "at least 12 characters" in r.json()["detail"]


def test_wizard_steps_after_owner_need_a_session(client: TestClient) -> None:
    assert client.post("/api/v1/setup/account", json={"name": "x"}).status_code == 401
    assert client.post("/api/v1/setup/complete").status_code == 401


def test_cannot_complete_without_an_account(client: TestClient) -> None:
    client.post("/api/v1/setup/owner", json={"username": "owner", "password": PASSWORD})
    assert client.post("/api/v1/setup/complete").status_code == 409
