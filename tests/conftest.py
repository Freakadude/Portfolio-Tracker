from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from folio.api.app import create_app
from folio.config import Settings
from folio.db import migrate
from folio.security.users import create_user

TEST_SECRET = "test-secret-key-0123456789abcdef0123456789abcdef"
USERNAME = "owner"
PASSWORD = "correct horse battery staple"
# An invented provider key for tests that save and mask one (the allow comment keeps the
# secret scanner quiet about this one clearly fake value).
FAKE_API_KEY = "fake-provider-key-0123456789"  # gitleaks:allow


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    url = f"sqlite:///{tmp_path / 'folio.db'}"
    migrate.upgrade(url)
    return Settings(  # type: ignore[call-arg]
        secret_key=TEST_SECRET,
        db_url=url,
        backup_dir=str(tmp_path / "backups"),  # never the real /data/backups of the machine
        _env_file=None,
    )


@pytest.fixture
def make_client(settings: Settings) -> Iterator[Callable[..., TestClient]]:
    clients: list[TestClient] = []

    def _make(base_url: str = "http://testserver", **app_kwargs: Any) -> TestClient:
        client = TestClient(create_app(settings, **app_kwargs), base_url=base_url)
        client.get("/api/v1/auth/me")  # primes the CSRF cookie
        client.headers["X-CSRF-Token"] = client.cookies.get("folio_csrf") or ""
        clients.append(client)
        return client

    yield _make
    for c in clients:
        c.close()


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client()


@pytest.fixture
def owner(settings: Settings) -> None:
    from folio.db.engine import make_engine, make_session_factory

    factory = make_session_factory(make_engine(settings.db_url))
    with factory() as db:
        create_user(db, USERNAME, PASSWORD)
        db.commit()
