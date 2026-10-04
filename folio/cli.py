import secrets
import signal
import threading
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from folio.config import get_settings
from folio.db import migrate as migrations
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import User
from folio.logging import configure_logging, get_logger
from folio.security.passwords import hash_password
from folio.security.users import MIN_PASSWORD_LENGTH, create_user, normalize_username

app = typer.Typer(help="Folio: self-hosted portfolio manager.", no_args_is_help=True)

ENV_FILE = Path(".env")


def _session_factory() -> sessionmaker[Session]:
    settings = get_settings()
    settings.require_secret_key()
    return make_session_factory(make_engine(settings.db_url))


@app.command()
def init(
    env_file: Annotated[Path, typer.Option(help="Where to write FOLIO_SECRET_KEY")] = ENV_FILE,
) -> None:
    """Generate FOLIO_SECRET_KEY into .env (never overwrites an existing key)."""
    existing = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    if any(
        line.startswith("FOLIO_SECRET_KEY=") and line.strip() != "FOLIO_SECRET_KEY="
        for line in existing.splitlines()
    ):
        typer.echo(f"{env_file} already has a FOLIO_SECRET_KEY; leaving it unchanged.")
        return
    lines = [ln for ln in existing.splitlines() if not ln.startswith("FOLIO_SECRET_KEY=")]
    lines.append(f"FOLIO_SECRET_KEY={secrets.token_urlsafe(48)}")
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    typer.echo(
        f"Wrote a new FOLIO_SECRET_KEY to {env_file}. Back it up: without it, stored keys "
        "cannot be decrypted."
    )


@app.command()
def migrate() -> None:
    """Apply database migrations."""
    migrations.upgrade(get_settings().db_url)
    typer.echo("Database is up to date.")


@app.command("create-user")
def create_user_cmd(
    username: Annotated[str, typer.Option(prompt=True)],
    password: Annotated[str, typer.Option(prompt=True, hide_input=True, confirmation_prompt=True)],
) -> None:
    """Create the owner account."""
    with _session_factory()() as db:
        try:
            user = create_user(db, username, password)
        except ValueError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(1) from exc
        db.commit()
    typer.echo(f"Created user {user.username}.")


@app.command("reset-password")
def reset_password(
    username: Annotated[str, typer.Option(prompt=True)],
    password: Annotated[str, typer.Option(prompt=True, hide_input=True, confirmation_prompt=True)],
) -> None:
    """Set a new password for an existing user."""
    if len(password) < MIN_PASSWORD_LENGTH:
        typer.echo(f"Error: password must be at least {MIN_PASSWORD_LENGTH} characters.", err=True)
        raise typer.Exit(1)
    with _session_factory()() as db:
        user = db.scalar(select(User).where(User.username == normalize_username(username)))
        if user is None:
            typer.echo("Error: no such user.", err=True)
            raise typer.Exit(1)
        user.password_hash = hash_password(password)
        db.commit()
    typer.echo("Password updated.")


@app.command()
def web(
    host: Annotated[str, typer.Option(envvar="FOLIO_HOST")] = "127.0.0.1",
    port: Annotated[int, typer.Option(envvar="FOLIO_PORT")] = 8080,
    reload: Annotated[bool, typer.Option(help="Auto-reload for development")] = False,
) -> None:
    """Run migrations, then serve the API and the built UI."""
    import uvicorn

    settings = get_settings()
    settings.require_secret_key()
    configure_logging(settings.log_level)
    migrations.upgrade(settings.db_url)
    uvicorn.run(
        "folio.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
        log_config=None,  # our JSON logging stays in charge
        access_log=False,  # the request middleware writes the access log
        proxy_headers=True,
    )


@app.command()
def worker() -> None:
    """Background worker. In Phase 0 it only heartbeats; jobs arrive in later phases."""
    settings = get_settings()
    settings.require_secret_key()
    configure_logging(settings.log_level)
    log = get_logger("folio.worker")
    stop = threading.Event()

    def _stop(signum: int, _frame: object) -> None:
        log.info("shutdown requested", signal=signum)
        stop.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    log.info("worker started")
    while not stop.wait(60):
        log.info("heartbeat")
    log.info("worker stopped")


if __name__ == "__main__":
    app()
