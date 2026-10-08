"""What the worker tells the web container about itself (FR-SY-10).

The two containers share the data folder, so the worker writes a small file there: when it
started, which build it runs and when it last looked up. The System page reads it to show how
long each container has been running, whether both run the same build, and whether the worker is
alive. The file holds no secrets and is not part of a backup.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from folio.config import Settings

FILE_NAME = "worker-status.json"
ALIVE_SECONDS = 180  # the worker writes every minute; three missed beats is not alive


@dataclass(frozen=True)
class WorkerStatus:
    build: str | None
    started_at: datetime
    seen_at: datetime

    def alive(self, now: datetime) -> bool:
        return (now - self.seen_at).total_seconds() <= ALIVE_SECONDS


def _path(settings: Settings) -> Path | None:
    prefix = "sqlite:///"
    if not settings.db_url.startswith(prefix) or ":memory:" in settings.db_url:
        return None
    return Path(settings.db_url[len(prefix) :]).parent / FILE_NAME


def write(settings: Settings, started_at: datetime, now: datetime) -> None:
    """Record that the worker started at `started_at` and is alive at `now`. A folder that cannot
    be written to must never stop the worker, so a failure is ignored."""
    path = _path(settings)
    if path is None:
        return
    body = {
        "build": settings.version,
        "started_at": started_at.astimezone(UTC).isoformat(),
        "seen_at": now.astimezone(UTC).isoformat(),
    }
    try:
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(body), encoding="utf-8")
        os.replace(temp, path)
    except OSError:
        return


def read(settings: Settings) -> WorkerStatus | None:
    """The worker's last report, or None when it never wrote one (or the file is unreadable)."""
    path = _path(settings)
    if path is None or not path.is_file():
        return None
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        return WorkerStatus(
            build=body.get("build"),
            started_at=datetime.fromisoformat(body["started_at"]),
            seen_at=datetime.fromisoformat(body["seen_at"]),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None
