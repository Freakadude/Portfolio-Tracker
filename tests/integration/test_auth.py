from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import User, UserSession
from tests.conftest import PASSWORD, USERNAME

LOGIN = "/api/v1/auth/login"


def login(client: TestClient, password: str = PASSWORD, remember: bool = False):  # type: ignore[no-untyped-def]
    return client.post(
        LOGIN, json={"username": USERNAME, "password": password, "remember": remember}
    )


def test_password_is_hashed_with_argon2id(settings: Settings, owner: None) -> None:
    with make_session_factory(make_engine(settings.db_url))() as db:
        user = db.scalar(select(User))
    assert user is not None
    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash


def test_login_me_logout(client: TestClient, owner: None) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401
    r = login(client)
    assert r.status_code == 200 and r.json() == {"username": USERNAME}
    assert client.get("/api/v1/auth/me").json() == {"username": USERNAME}
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_wrong_credentials_are_a_plain_problem_response(client: TestClient, owner: None) -> None:
    r = login(client, "wrong password!!")
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["title"] == "Wrong username or password"
    unknown = client.post(LOGIN, json={"username": "nobody", "password": "x" * 14})
    assert unknown.json()["title"] == r.json()["title"]  # no username enumeration


def test_session_cookie_flags_over_http(client: TestClient, owner: None) -> None:
    cookie = login(client).headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "secure" not in cookie
    assert "max-age" not in cookie  # browser-session cookie unless remembered


def test_session_cookie_is_secure_over_https(
    make_client: Callable[..., TestClient], owner: None
) -> None:
    client = make_client("https://testserver")
    cookie = login(client).headers["set-cookie"].lower()
    assert "secure" in cookie and "httponly" in cookie and "samesite=strict" in cookie


def test_remember_device_lasts_30_days(client: TestClient, settings: Settings, owner: None) -> None:
    r = login(client, remember=True)
    assert f"max-age={30 * 24 * 3600}" in r.headers["set-cookie"].lower()
    with make_session_factory(make_engine(settings.db_url))() as db:
        row = db.scalar(select(UserSession))
    assert row is not None and row.remember
    remaining = row.expires_at - datetime.now(UTC)
    assert timedelta(days=29, hours=23) < remaining <= timedelta(days=30)


def test_brute_force_is_throttled(client: TestClient, owner: None) -> None:
    for _ in range(5):
        assert login(client, "wrong password!!").status_code == 401
    r = login(client, "wrong password!!")
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) > 0
    # even the right password is refused while throttled
    assert login(client).status_code == 429


def test_throttle_survives_restart(make_client: Callable[..., TestClient], owner: None) -> None:
    first = make_client()
    for _ in range(5):
        login(first, "wrong password!!")
    second = make_client()  # a fresh app instance on the same database
    assert login(second).status_code == 429


def test_expired_session_is_rejected(client: TestClient, settings: Settings, owner: None) -> None:
    login(client)
    factory = make_session_factory(make_engine(settings.db_url))
    with factory() as db:
        row = db.scalar(select(UserSession))
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401
