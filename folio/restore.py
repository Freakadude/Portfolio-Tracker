"""Restoring a backup from the web app (FR-SY-07).

A running app cannot swap its own database file safely, so a restore is done in two steps. The web
app verifies the chosen backup and *stages* it beside the database (`folio.db.restore-pending`),
answers, and exits; the container restarts. On start, before anything opens the database, the
staged file is swapped in by `backup.restore_backup` (which keeps a `pre-restore` copy of what was
there and migrates the restored database forward) and the outcome is written to a small result
file. The worker watches that file and restarts too, so both processes use the restored database.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from folio.backup import BackupError, restore_backup, sqlite_path, verify_backup

PENDING_SUFFIX = ".restore-pending"
RESULT_SUFFIX = ".restore-result.json"
EXIT_DELAY_SECONDS = 1.5


@dataclass(frozen=True)
class Staged:
    path: Path
    label: str


def pending_path(db_url: str) -> Path:
    db = sqlite_path(db_url)
    return db.with_name(db.name + PENDING_SUFFIX)


def _sidecar(db_url: str) -> Path:
    pending = pending_path(db_url)
    return pending.with_name(pending.name + ".json")


def result_path(db_url: str) -> Path:
    db = sqlite_path(db_url)
    return db.with_name(db.name + RESULT_SUFFIX)


def stage(db_url: str, source: Path, label: str) -> Staged:
    """Verify `source` and put a copy beside the database to be swapped in at the next start."""
    verify_backup(source)
    target = pending_path(db_url)
    shutil.copy2(source, target)
    _sidecar(db_url).write_text(json.dumps({"label": label}), encoding="utf-8")
    return Staged(target, label)


def is_pending(db_url: str) -> bool:
    try:
        return pending_path(db_url).is_file()
    except BackupError:
        return False


def apply_pending(
    db_url: str, backup_dir: str | Path, now: datetime | None = None
) -> dict[str, Any] | None:
    """Swap in a staged backup, if there is one. Called before the database is opened. Returns
    what happened (also written to the result file), or None when nothing was staged."""
    try:
        pending = pending_path(db_url)
    except BackupError:
        return None  # not a file-based database: there is nothing to stage
    if not pending.is_file():
        return None
    sidecar = _sidecar(db_url)
    label = ""
    if sidecar.is_file():
        try:
            label = str(json.loads(sidecar.read_text(encoding="utf-8")).get("label", ""))
        except ValueError:
            label = ""
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    outcome: dict[str, Any] = {"at": moment.isoformat(), "from": label, "ok": False}
    try:
        done = restore_backup(pending, db_url, backup_dir, now=moment)
        outcome.update(
            ok=True, safety_copy=None if done.safety_copy is None else done.safety_copy.name
        )
    except BackupError as exc:
        failed = pending.with_name(pending.name + ".failed")
        pending.replace(failed)  # kept for a look, never applied twice
        outcome["error"] = str(exc)
    finally:
        pending.unlink(missing_ok=True)
        sidecar.unlink(missing_ok=True)
    result_path(db_url).write_text(json.dumps(outcome), encoding="utf-8")
    return outcome


def last_result(db_url: str) -> dict[str, Any] | None:
    try:
        path = result_path(db_url)
    except BackupError:
        return None
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def result_stamp(db_url: str) -> float | None:
    """A value that changes when a restore has just been applied, for the worker to notice."""
    try:
        path = result_path(db_url)
    except BackupError:
        return None
    return path.stat().st_mtime_ns if path.is_file() else None


def exit_soon() -> None:
    """Let the response go out, then stop this process so the container restarts it (the stack
    restarts its containers unless they are stopped by hand)."""
    threading.Timer(EXIT_DELAY_SECONDS, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
