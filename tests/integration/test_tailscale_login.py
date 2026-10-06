"""Sign-in through Tailscale Serve (FR-SY-04) end to end: off by default, and refused from any
connection that is not the named address or names another user."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from folio.api.app import create_app
from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import AuditLog
from folio.security.tailscale import HEADER
from tests.conftest import USERNAME

PROXY = "172.18.0.1"
LOGIN = "you@example.com"


def client_for(settings: Settings, peer: str, user: str | None = LOGIN, proxies: str = PROXY):  # type: ignore[no-untyped-def]
    configured = settings.model_copy(update={"tailscale_user": user, "trusted_proxies": proxies})
    client = TestClient(create_app(configured), client=(peer, 50000))
    client.get("/api/v1/auth/me")  # primes the CSRF cookie
    client.headers["X-CSRF-Token"] = client.cookies.get("folio_csrf") or ""
    return client


@pytest.fixture
def through(settings: Settings, owner: None) -> TestClient:
    """A connection from Tailscale Serve's address, naming the configured user."""
    client = client_for(settings, PROXY)
    client.headers[HEADER] = LOGIN
    return client


def test_a_request_through_the_named_address_as_the_named_user_signs_in_the_owner(
    through: TestClient, settings: Settings
) -> None:
    assert through.get("/api/v1/auth/methods").json() == {"tailscale": True}
    assert through.get("/api/v1/auth/me").status_code == 401  # nothing is granted by looking
    r = through.post("/api/v1/auth/tailscale")
    assert r.status_code == 200 and r.json() == {"username": USERNAME}
    assert through.get("/api/v1/auth/me").json() == {"username": USERNAME}
    with make_session_factory(make_engine(settings.db_url))() as db:
        row = db.scalars(select(AuditLog).where(AuditLog.action == "sign in with Tailscale")).one()
    assert row.diff == {"tailnet_login": LOGIN}


def test_the_header_from_any_other_address_is_ignored(settings: Settings, owner: None) -> None:
    for peer in ("172.18.0.2", "192.168.1.50", "127.0.0.1"):
        client = client_for(settings, peer)
        client.headers[HEADER] = LOGIN  # anyone can write this
        assert client.get("/api/v1/auth/methods").json() == {"tailscale": False}, peer
        refused = client.post("/api/v1/auth/tailscale")
        assert refused.status_code == 401 and client.get("/api/v1/auth/me").status_code == 401


def test_another_tailnet_user_or_no_header_is_refused(settings: Settings, owner: None) -> None:
    other = client_for(settings, PROXY)
    other.headers[HEADER] = "someone@else.com"
    assert other.post("/api/v1/auth/tailscale").status_code == 401
    bare = client_for(settings, PROXY)
    assert bare.get("/api/v1/auth/methods").json() == {"tailscale": False}
    assert bare.post("/api/v1/auth/tailscale").status_code == 401


def test_it_is_off_by_default_and_unless_both_settings_are_present(
    settings: Settings, owner: None
) -> None:
    for user, proxies in ((None, PROXY), (LOGIN, "")):
        client = client_for(settings, PROXY, user=user, proxies=proxies)
        client.headers[HEADER] = LOGIN
        assert client.get("/api/v1/auth/methods").json() == {"tailscale": False}
        assert client.post("/api/v1/auth/tailscale").status_code == 401
    plain = TestClient(create_app(settings), client=(PROXY, 1))
    plain.headers[HEADER] = LOGIN
    assert plain.get("/api/v1/auth/methods").json() == {"tailscale": False}


def test_a_tailnet_sign_in_does_not_ask_for_the_second_factor_but_the_password_still_does(
    settings: Settings, owner: None
) -> None:
    from datetime import UTC, datetime

    from folio.security import twofactor

    with make_session_factory(make_engine(settings.db_url))() as db:
        from folio.db.models import User

        user = db.scalar(select(User))
        secret, _ = twofactor.start_setup(db, user, settings.secret_key)
        from folio.security import totp

        twofactor.enable(
            db,
            user,
            totp.code_at(secret, datetime.now(UTC)),
            datetime.now(UTC),
            settings.secret_key,
        )
        db.commit()
    client = client_for(settings, PROXY)
    client.headers[HEADER] = LOGIN
    assert client.post("/api/v1/auth/tailscale").status_code == 200
    plain = TestClient(create_app(settings), client=("192.168.1.5", 1))
    plain.get("/api/v1/auth/me")
    plain.headers["X-CSRF-Token"] = plain.cookies.get("folio_csrf") or ""
    from tests.conftest import PASSWORD

    needs = plain.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    assert needs.status_code == 401 and needs.json()["code"] == "totp_required"
