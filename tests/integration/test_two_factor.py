"""The optional second factor (FR-SY-03): a code at sign-in once it is on, recovery codes for a
lost phone, and the protections around turning it off."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from folio.api.routers import auth as auth_router
from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import AuditLog, RecoveryCode, User
from folio.security import totp
from tests.conftest import PASSWORD, USERNAME

LOGIN = "/api/v1/auth/login"
NOW = datetime(2026, 10, 6, 12, 0, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now

    def later(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    c = Clock()
    monkeypatch.setattr(auth_router, "utcnow", c)
    return c


@pytest.fixture
def api(make_client: Callable[..., TestClient], owner: None, clock: Clock) -> TestClient:
    c = make_client()
    assert c.post(LOGIN, json={"username": USERNAME, "password": PASSWORD}).status_code == 200
    return c


@pytest.fixture
def fresh(make_client: Callable[..., TestClient], owner: None) -> TestClient:
    """Another browser: nobody signed in."""
    return make_client()


def secret_of(setup: dict[str, str]) -> str:
    return setup["secret"].replace(" ", "")


def turn_on(api: TestClient, clock: Clock) -> tuple[str, list[str]]:
    setup = api.post("/api/v1/auth/totp/setup").json()
    secret = secret_of(setup)
    done = api.post("/api/v1/auth/totp/enable", json={"code": totp.code_at(secret, clock.now)})
    assert done.status_code == 200, done.text
    clock.later(30)  # the code that confirmed it cannot be used again
    return secret, done.json()["recovery_codes"]


def sign_in(client: TestClient, code: str | None = None):  # type: ignore[no-untyped-def]
    body = {"username": USERNAME, "password": PASSWORD}
    if code is not None:
        body["code"] = code
    return client.post(LOGIN, json=body)


# --- setting it up ------------------------------------------------------------------------------


def test_setup_gives_a_qr_code_and_the_secret_and_changes_nothing_until_confirmed(
    api: TestClient, fresh: TestClient, settings: Settings
) -> None:
    assert api.get("/api/v1/auth/totp").json() == {
        "enabled": False,
        "pending": False,
        "recovery_codes_left": 0,
    }
    setup = api.post("/api/v1/auth/totp/setup").json()
    assert setup["qr_svg"].startswith("<svg") and setup["uri"].startswith("otpauth://totp/Folio")
    secret = secret_of(setup)
    assert f"secret={secret}" in setup["uri"] and len(secret) == 32 and " " in setup["secret"]
    assert api.get("/api/v1/auth/totp").json()["pending"] is True
    assert sign_in(fresh).status_code == 200  # a half-finished setup never locks you out
    with make_session_factory(make_engine(settings.db_url))() as db:
        stored = db.scalar(select(User)).totp_secret_enc
    assert stored and secret not in stored  # kept encrypted


def test_a_wrong_code_does_not_turn_it_on_and_the_right_one_does_with_ten_recovery_codes(
    api: TestClient, clock: Clock
) -> None:
    secret = secret_of(api.post("/api/v1/auth/totp/setup").json())
    wrong = api.post("/api/v1/auth/totp/enable", json={"code": "000000"})
    assert wrong.status_code == 422 and "not right" in wrong.json()["detail"]
    assert api.get("/api/v1/auth/totp").json()["enabled"] is False
    ok = api.post("/api/v1/auth/totp/enable", json={"code": totp.code_at(secret, clock.now)})
    codes = ok.json()["recovery_codes"]
    assert len(codes) == 10 and len(set(codes)) == 10
    assert api.get("/api/v1/auth/totp").json() == {
        "enabled": True,
        "pending": False,
        "recovery_codes_left": 10,
    }
    assert api.post("/api/v1/auth/totp/setup").status_code == 409  # already on


def test_only_hashes_of_the_recovery_codes_are_kept(
    api: TestClient, clock: Clock, settings: Settings
) -> None:
    _, codes = turn_on(api, clock)
    with make_session_factory(make_engine(settings.db_url))() as db:
        hashes = [r.code_hash for r in db.scalars(select(RecoveryCode))]
    assert len(hashes) == 10 and all(h.startswith("$argon2id$") for h in hashes)
    assert not any(code.replace("-", "") in h for code in codes for h in hashes)


# --- signing in ---------------------------------------------------------------------------------


def test_sign_in_needs_the_code_once_it_is_on(
    api: TestClient, fresh: TestClient, clock: Clock
) -> None:
    secret, _ = turn_on(api, clock)
    needed = sign_in(fresh)
    assert needed.status_code == 401 and needed.json()["code"] == "totp_required"
    assert needed.json()["title"] == "Code needed"
    assert fresh.get("/api/v1/auth/me").status_code == 401  # nothing was granted
    wrong = sign_in(fresh, "123456")
    assert wrong.status_code == 401 and wrong.json()["title"] == "Wrong code"
    ok = sign_in(fresh, totp.code_at(secret, clock.now))
    assert ok.status_code == 200 and fresh.get("/api/v1/auth/me").json() == {"username": USERNAME}


def test_a_code_works_once_and_the_next_one_works(
    api: TestClient, make_client: Callable[..., TestClient], clock: Clock
) -> None:
    secret, _ = turn_on(api, clock)
    code = totp.code_at(secret, clock.now)
    assert sign_in(make_client(), code).status_code == 200
    replay = sign_in(make_client(), code)  # the same code, seen again
    assert replay.status_code == 401 and replay.json()["title"] == "Wrong code"
    clock.later(30)
    assert sign_in(make_client(), totp.code_at(secret, clock.now)).status_code == 200


def test_a_wrong_password_never_gets_as_far_as_asking_for_the_code(
    api: TestClient, fresh: TestClient, clock: Clock
) -> None:
    turn_on(api, clock)
    r = fresh.post(LOGIN, json={"username": USERNAME, "password": "wrong password!!"})
    assert r.json()["title"] == "Wrong username or password" and "code" not in r.json()


def test_a_recovery_code_works_once(
    api: TestClient, make_client: Callable[..., TestClient], clock: Clock
) -> None:
    _, codes = turn_on(api, clock)
    assert sign_in(make_client(), codes[0].lower()).status_code == 200  # case does not matter
    assert api.get("/api/v1/auth/totp").json()["recovery_codes_left"] == 9
    again = sign_in(make_client(), codes[0])
    assert again.status_code == 401 and again.json()["title"] == "Wrong code"
    assert sign_in(make_client(), codes[1].replace("-", " ")).status_code == 200


def test_five_wrong_codes_lock_the_sign_in_for_a_while(
    api: TestClient, make_client: Callable[..., TestClient], clock: Clock
) -> None:
    secret, _ = turn_on(api, clock)
    attacker = make_client()
    for _ in range(5):
        assert sign_in(attacker, "000000").status_code == 401
    locked = sign_in(attacker, totp.code_at(secret, clock.now))
    assert locked.status_code == 429 and "retry-after" in locked.headers


def test_a_code_with_odd_characters_is_a_plain_refusal_not_an_error(
    api: TestClient, fresh: TestClient, clock: Clock
) -> None:
    turn_on(api, clock)
    assert sign_in(fresh, "28708２").status_code == 401  # a full-width digit
    assert sign_in(fresh, "   ").json()["code"] == "totp_required"


# --- turning it off and replacing the codes -----------------------------------------------------


def test_turning_it_off_needs_the_password_and_a_code_and_removes_everything(
    api: TestClient, fresh: TestClient, clock: Clock, settings: Settings
) -> None:
    secret, _ = turn_on(api, clock)
    code = totp.code_at(secret, clock.now)
    url = "/api/v1/auth/totp/disable"
    bad_password = api.post(url, json={"password": "nope nope nope", "code": code})
    assert bad_password.status_code == 422 and "password" in bad_password.json()["detail"]
    bad_code = api.post(url, json={"password": PASSWORD, "code": "111111"})
    assert bad_code.status_code == 422 and api.get("/api/v1/auth/totp").json()["enabled"] is True
    assert api.post(url, json={"password": PASSWORD, "code": code}).status_code == 204
    assert api.get("/api/v1/auth/totp").json() == {
        "enabled": False,
        "pending": False,
        "recovery_codes_left": 0,
    }
    assert sign_in(fresh).status_code == 200  # no code needed again
    with make_session_factory(make_engine(settings.db_url))() as db:
        assert db.scalars(select(RecoveryCode)).all() == []
        assert db.scalar(select(User)).totp_secret_enc is None


def test_new_recovery_codes_replace_the_old_ones(
    api: TestClient, make_client: Callable[..., TestClient], clock: Clock
) -> None:
    secret, old = turn_on(api, clock)
    code = totp.code_at(secret, clock.now)
    url = "/api/v1/auth/totp/recovery-codes"
    new = api.post(url, json={"password": PASSWORD, "code": code})
    fresh_codes = new.json()["recovery_codes"]
    assert new.status_code == 200 and len(fresh_codes) == 10 and not set(fresh_codes) & set(old)
    assert sign_in(make_client(), old[0]).status_code == 401  # no longer worth anything
    assert sign_in(make_client(), fresh_codes[0]).status_code == 200
    assert api.post(url, json={"password": PASSWORD, "code": "000000"}).status_code == 422


def test_turning_it_on_and_off_is_audited_without_any_secret(
    api: TestClient, clock: Clock, settings: Settings
) -> None:
    secret, codes = turn_on(api, clock)
    api.post(
        "/api/v1/auth/totp/disable",
        json={"password": PASSWORD, "code": totp.code_at(secret, clock.now)},
    )
    with make_session_factory(make_engine(settings.db_url))() as db:
        rows = db.scalars(select(AuditLog).where(AuditLog.entity == "user")).all()
    assert [r.action for r in rows] == ["second factor on", "second factor off"]
    shown = " ".join(str(r.diff) for r in rows)
    assert secret not in shown and codes[0] not in shown


def test_the_second_factor_endpoints_need_a_sign_in(fresh: TestClient) -> None:
    assert fresh.get("/api/v1/auth/totp").status_code == 401
    assert fresh.post("/api/v1/auth/totp/setup").status_code == 401
    assert fresh.post("/api/v1/auth/totp/enable", json={"code": "123456"}).status_code == 401
    body = {"password": PASSWORD, "code": "123456"}
    assert fresh.post("/api/v1/auth/totp/disable", json=body).status_code == 401
    assert fresh.post("/api/v1/auth/totp/recovery-codes", json=body).status_code == 401
