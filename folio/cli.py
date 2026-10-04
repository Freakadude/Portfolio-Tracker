import secrets
import signal
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.backup import (
    BackupError,
    backup_before_migration,
    create_backup,
    restore_backup,
)
from folio.config import get_settings
from folio.db import migrate as migrations
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import User
from folio.demo import DemoError, seed_demo
from folio.logging import configure_logging, get_logger
from folio.security.passwords import hash_password
from folio.security.users import MIN_PASSWORD_LENGTH, create_user, normalize_username

app = typer.Typer(help="Folio: self-hosted portfolio manager.", no_args_is_help=True)

ENV_FILE = Path(".env")


@contextmanager
def _session() -> Iterator[Session]:
    """A database session that releases the file when the command is done."""
    settings = get_settings()
    settings.require_secret_key()
    engine = make_engine(settings.db_url)
    try:
        with make_session_factory(engine)() as db:
            yield db
    finally:
        engine.dispose()


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


def _migrate_safely(settings) -> None:  # type: ignore[no-untyped-def]
    """Migrate, after copying an existing database that is about to change (forward-only)."""
    copy = backup_before_migration(settings.db_url, settings.backup_dir)
    if copy is not None:
        get_logger("folio.migrate").info("backup before migration", file=str(copy))
    migrations.upgrade(settings.db_url)


@app.command()
def migrate() -> None:
    """Apply database migrations (a backup is taken first when the schema will change)."""
    _migrate_safely(get_settings())
    typer.echo("Database is up to date.")


@app.command("create-user")
def create_user_cmd(
    username: Annotated[str, typer.Option(prompt=True)],
    password: Annotated[str, typer.Option(prompt=True, hide_input=True, confirmation_prompt=True)],
) -> None:
    """Create the owner account."""
    with _session() as db:
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
    with _session() as db:
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
    _migrate_safely(settings)
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
    """Background worker: scheduled prices, rates, snapshots and backups, plus the queue of
    requests made in the web app."""
    from folio.jobs.context import build_context
    from folio.jobs.scheduler import make_scheduler

    settings = get_settings()
    settings.require_secret_key()
    configure_logging(settings.log_level)
    log = get_logger("folio.worker")
    ctx = build_context(settings)
    scheduler = make_scheduler(settings, ctx)
    stop = threading.Event()

    def _stop(signum: int, _frame: object) -> None:
        log.info("shutdown requested", signal=signum)
        stop.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    scheduler.start()
    log.info("worker started", jobs=[job.id for job in scheduler.get_jobs()])
    stop.wait()
    scheduler.shutdown(wait=True)
    log.info("worker stopped")


@app.command()
def backup(
    no_secrets: Annotated[
        bool, typer.Option("--no-secrets", help="Remove stored API keys (for copies you share)")
    ] = False,
    directory: Annotated[Path | None, typer.Option("--dir", help="Backup folder")] = None,
) -> None:
    """Write a verified backup of the database now."""
    settings = get_settings()
    try:
        result = create_backup(
            settings.db_url,
            directory or settings.backup_dir,
            extra_dir=settings.extra_backup_dir,
            include_secrets=not no_secrets,
        )
    except BackupError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Backup written to {result.path} ({result.size} bytes, integrity ok).")
    if result.copied_to:
        typer.echo(f"Copied to {result.copied_to}.")
    if result.pruned:
        typer.echo(f"Removed {len(result.pruned)} old backup(s).")


@app.command()
def restore(
    file: Annotated[Path, typer.Argument(help="A backup file made by `folio backup`")],
    yes: Annotated[bool, typer.Option("--yes", help="Do not ask for confirmation")] = False,
) -> None:
    """Replace the database with a backup. Stop the web and worker containers first."""
    settings = get_settings()
    if not yes:
        typer.confirm(
            f"This replaces the current database with {file}. The current one is kept as a "
            "pre-restore copy. Continue?",
            abort=True,
        )
    try:
        result = restore_backup(file, settings.db_url, settings.backup_dir)
    except BackupError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    if result.safety_copy:
        typer.echo(f"The previous database was saved as {result.safety_copy}.")
    typer.echo(f"Restored from {result.restored_from}. Start the web and worker again.")


@app.command("run-job")
def run_job_cmd(
    name: Annotated[
        str, typer.Argument(help="eod, fx, gaps, snapshots, actions, backfill, backup")
    ],
    param: Annotated[
        list[str] | None,
        typer.Option("--param", "-p", help="key=value, for example mic=XETR or listing_id=3"),
    ] = None,
) -> None:
    """Run one job now and print its log."""
    from folio.jobs.context import build_context
    from folio.jobs.scheduler import handlers

    settings = get_settings()
    settings.require_secret_key()
    configure_logging(settings.log_level)
    table = handlers(build_context(settings), settings)
    if name not in table:
        typer.echo(
            f"Error: unknown job {name!r}. Choose from: {', '.join(sorted(table))}.", err=True
        )
        raise typer.Exit(1)
    params: dict[str, object] = {}
    for item in param or []:
        key, _, value = item.partition("=")
        params[key] = value
    try:
        result = table[name](params)
    except KeyError as exc:
        typer.echo(f"Error: the {name} job needs --param {exc.args[0]}=...", err=True)
        raise typer.Exit(1) from exc
    typer.echo(result.log or "(no output)")
    if result.status != "ok":
        raise typer.Exit(1)


@app.command()
def seed(
    demo: Annotated[bool, typer.Option("--demo", help="Add a fictional demo portfolio")] = False,
) -> None:
    """Add fictional data for working on the UI (never real holdings)."""
    if not demo:
        typer.echo("Error: only `folio seed --demo` is available.", err=True)
        raise typer.Exit(1)
    with _session() as db:
        try:
            counts = seed_demo(db, date.today())
        except DemoError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(1) from exc
        db.commit()
    typer.echo(
        f"Added {counts['instruments']} instruments, {counts['transactions']} transactions and "
        f"{counts['snapshots']} daily snapshots (all fictional)."
    )


if __name__ == "__main__":
    app()
