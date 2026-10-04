from pathlib import Path

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from folio.cli import app
from folio.config import Settings, get_settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import User
from folio.security.passwords import verify_password

runner = CliRunner()


def test_init_writes_key_once(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("FOLIO_LAN_IP=10.0.0.5\nFOLIO_SECRET_KEY=\n")
    assert runner.invoke(app, ["init", "--env-file", str(env)]).exit_code == 0
    first = env.read_text()
    key = next(ln for ln in first.splitlines() if ln.startswith("FOLIO_SECRET_KEY=")).split("=", 1)[
        1
    ]
    assert len(key) >= 32 and "FOLIO_LAN_IP=10.0.0.5" in first
    again = runner.invoke(app, ["init", "--env-file", str(env)])
    assert "leaving it unchanged" in again.output and env.read_text() == first


@pytest.fixture
def cli_env(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("FOLIO_SECRET_KEY", settings.secret_key)
    monkeypatch.setenv("FOLIO_DB_URL", settings.db_url)
    get_settings.cache_clear()
    yield settings  # type: ignore[misc]
    get_settings.cache_clear()


def test_create_user_and_reset_password(cli_env: Settings) -> None:
    ok = runner.invoke(app, ["create-user", "--username", "Owner", "--password", "twelve chars ok"])
    assert ok.exit_code == 0, ok.output
    dup = runner.invoke(
        app, ["create-user", "--username", "owner", "--password", "twelve chars ok"]
    )
    assert dup.exit_code == 1 and "already exists" in dup.output
    weak = runner.invoke(app, ["reset-password", "--username", "owner", "--password", "short"])
    assert weak.exit_code == 1
    reset = runner.invoke(
        app, ["reset-password", "--username", "owner", "--password", "brand new passphrase"]
    )
    assert reset.exit_code == 0
    with make_session_factory(make_engine(cli_env.db_url))() as db:
        user = db.scalar(select(User))
    assert user is not None and verify_password(user.password_hash, "brand new passphrase")
    assert not verify_password(user.password_hash, "twelve chars ok")


def test_migrate_command(cli_env: Settings) -> None:
    assert runner.invoke(app, ["migrate"]).exit_code == 0
