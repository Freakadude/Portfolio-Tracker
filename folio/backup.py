"""Online backups of the SQLite database and restore (FR-SY-06, FR-SY-07).

A backup is made with `VACUUM INTO`, which writes a consistent copy while the app keeps running.
Every backup is checked with `PRAGMA integrity_check` before it counts. Retention keeps the 14
newest backups plus the newest one from each of the 8 previous weeks. A restore verifies the
file, takes a safety copy of the current database, swaps the file in, and migrates it forward.
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from folio.db import migrate

DAILY_KEEP = 14
WEEKLY_KEEP = 8
OTHER_KEEP = 5  # pre-migration and pre-restore copies
_NAME = re.compile(r"^(?P<prefix>folio|pre-migrate|pre-restore)-(?P<stamp>\d{8}-\d{6})(-\d+)?\.db$")


class BackupError(Exception):
    """A backup or restore cannot proceed; the message is for the owner."""


@dataclass(frozen=True)
class BackupResult:
    path: Path
    size: int
    copied_to: Path | None = None
    pruned: list[Path] = field(default_factory=list)


def sqlite_path(db_url: str) -> Path:
    url = make_url(db_url)
    if url.get_backend_name() != "sqlite" or url.database in (None, "", ":memory:"):
        raise BackupError(
            "Backups with this command work for file-based SQLite databases. For PostgreSQL use "
            "pg_dump."
        )
    return Path(str(url.database))


def verify_backup(path: Path) -> None:
    """The file opens, passes SQLite's integrity check and is a Folio database."""
    if not path.is_file():
        raise BackupError(f"{path} does not exist.")
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            result = con.execute("PRAGMA integrity_check").fetchall()
            tables = {
                r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        finally:
            con.close()
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"{path.name} is not a valid database file ({exc}).") from exc
    if result != [("ok",)]:
        raise BackupError(f"{path.name} failed the integrity check: {result[0][0]}")
    if not {"alembic_version", "app_user"} <= tables:
        raise BackupError(f"{path.name} is a database, but not a Folio database.")


def _free_name(directory: Path, prefix: str, now: datetime) -> Path:
    base = f"{prefix}-{now.astimezone(UTC).strftime('%Y%m%d-%H%M%S')}"
    candidate, n = directory / f"{base}.db", 1
    while candidate.exists():
        n += 1
        candidate = directory / f"{base}-{n}.db"
    return candidate


def create_backup(
    db_url: str,
    backup_dir: str | Path,
    *,
    extra_dir: str | Path | None = None,
    include_secrets: bool = True,
    now: datetime | None = None,
    prefix: str = "folio",
) -> BackupResult:
    """Write a verified backup, optionally copy it to a second folder (a NAS mount), and prune
    old ones. Secrets are stored encrypted in the database; `include_secrets=False` removes
    them, which is what a copy that leaves your machine should use."""
    source = sqlite_path(db_url)
    if not source.is_file():
        raise BackupError(f"There is no database at {source} yet.")
    directory = Path(backup_dir)
    directory.mkdir(parents=True, exist_ok=True)
    moment = now or datetime.now(UTC)
    target = _free_name(directory, prefix, moment)

    con = sqlite3.connect(source, timeout=30)
    try:
        con.execute("VACUUM INTO ?", (str(target),))
    finally:
        con.close()
    try:
        if not include_secrets:
            copy = sqlite3.connect(target)
            try:
                copy.execute("DELETE FROM secret")
                copy.commit()
                copy.execute("VACUUM")
            finally:
                copy.close()
        verify_backup(target)
    except BackupError:
        target.unlink(missing_ok=True)  # a backup that does not verify is not kept
        raise

    copied: Path | None = None
    if extra_dir:
        extra = Path(extra_dir)
        extra.mkdir(parents=True, exist_ok=True)
        copied = extra / target.name
        shutil.copy2(target, copied)
    return BackupResult(target, target.stat().st_size, copied, prune(directory))


def _stamp(path: Path) -> datetime | None:
    match = _NAME.match(path.name)
    if match is None:
        return None
    return datetime.strptime(match["stamp"], "%Y%m%d-%H%M%S").replace(tzinfo=UTC)


def prune(directory: Path) -> list[Path]:
    """Keep the newest 14 backups and the newest of each of the 8 previous weeks; keep the
    last 5 pre-migration and pre-restore copies. Other files are never touched."""
    groups: dict[str, list[tuple[datetime, Path]]] = {}
    for path in directory.glob("*.db"):
        match = _NAME.match(path.name)
        stamp = _stamp(path)
        if match is not None and stamp is not None:
            groups.setdefault(match["prefix"], []).append((stamp, path))
    removed: list[Path] = []
    for prefix, items in groups.items():
        items.sort(key=lambda item: (item[0], item[1].name), reverse=True)  # newest first
        if prefix != "folio":
            doomed = [p for _, p in items[OTHER_KEEP:]]
        else:
            rest = items[DAILY_KEEP:]
            kept_weeks: list[tuple[int, int]] = []
            doomed = []
            for stamp, path in rest:
                iso = stamp.isocalendar()
                week = (iso.year, iso.week)
                if week in kept_weeks:
                    doomed.append(path)  # an older copy from a week already kept
                elif len(kept_weeks) < WEEKLY_KEEP:
                    kept_weeks.append(week)
                else:
                    doomed.append(path)
        for path in doomed:
            path.unlink(missing_ok=True)
            removed.append(path)
    return removed


@dataclass(frozen=True)
class RestoreResult:
    restored_from: Path
    safety_copy: Path | None


def restore_backup(
    source: str | Path, db_url: str, backup_dir: str | Path, *, now: datetime | None = None
) -> RestoreResult:
    """Replace the database with a backup. Stop the web and worker containers first: the file
    is swapped in place. The current database is kept as a `pre-restore` copy, and the restored
    one is migrated to the current schema."""
    path = Path(source)
    verify_backup(path)
    target = sqlite_path(db_url)
    safety: Path | None = None
    if target.is_file():
        safety = create_backup(db_url, backup_dir, prefix="pre-restore", now=now).path
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(target.name + ".restoring")
    shutil.copy2(path, staging)
    try:
        for suffix in ("-wal", "-shm"):
            Path(str(target) + suffix).unlink(missing_ok=True)
        os.replace(staging, target)
    except OSError as exc:
        staging.unlink(missing_ok=True)
        raise BackupError(
            f"The database file is in use ({exc}). Stop the web and worker first, then retry."
        ) from exc
    migrate.upgrade(db_url)
    return RestoreResult(path, safety)


def backup_before_migration(db_url: str, backup_dir: str | Path) -> Path | None:
    """A safety copy taken automatically before migrations run on an existing database."""
    try:
        source = sqlite_path(db_url)
    except BackupError:
        return None
    if not source.is_file():
        return None
    from folio.db.engine import make_engine

    engine = make_engine(db_url)
    try:
        if migrate.is_at_head(engine):
            return None
        tables = (
            sqlite3.connect(source)
            .execute("SELECT 1 FROM sqlite_master WHERE name='alembic_version'")
            .fetchone()
        )
        if tables is None:
            return None  # a brand-new, empty file: nothing to protect
    finally:
        engine.dispose()
    return create_backup(db_url, backup_dir, prefix="pre-migrate").path
