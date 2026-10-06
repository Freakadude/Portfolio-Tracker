"""Backups in the web app (FR-SY-07): list, make one now, download, upload, and restore.

A restore does not happen under the running app: the chosen backup is verified and staged, the
response says so, and the process stops so the container restarts; the swap is done on start
(`folio.restore`). Downloads leave out the stored API keys unless asked.
"""

import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, File, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from folio import restore
from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.audit import write_audit
from folio.backup import BackupError, create_backup, stripped_copy, verify_backup

router = APIRouter(prefix="/system", tags=["system"])

NAME = re.compile(
    r"^(?P<kind>folio|pre-migrate|pre-restore|upload)-(?P<stamp>\d{8}-\d{6})(-\d+)?\.db$"
)
MAX_UPLOAD = 512 * 1024 * 1024
CONFIRM = "RESTORE"

Kind = Literal["folio", "pre-migrate", "pre-restore", "upload"]


class BackupOut(BaseModel):
    name: str
    kind: Kind
    size: int
    created_at: datetime


class BackupMakeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_secrets: bool = True  # a backup kept on the server holds the encrypted API keys


class RestoreIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    confirm: str = Field(max_length=20)  # the word RESTORE, typed


class RestoreStartedOut(BaseModel):
    restarting: bool
    note: str


class RestoreResultOut(BaseModel):
    at: datetime
    source: str  # the backup that was restored
    ok: bool
    safety_copy: str | None  # what was there before, kept as a pre-restore copy
    error: str | None


class RestoreStatusOut(BaseModel):
    pending: bool  # a restore is staged and waits for the restart
    last: RestoreResultOut | None


def _directory(request: Request) -> Path:
    return Path(request.app.state.settings.backup_dir)


def _out(path: Path) -> BackupOut:
    match = NAME.match(path.name)
    if match is None:  # callers only pass names this module accepts
        raise ValueError(f"{path.name} is not a backup name")
    created = datetime.strptime(match["stamp"], "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
    return BackupOut(
        name=path.name,
        kind=match["kind"],
        size=path.stat().st_size,
        created_at=created,
    )


def _file(request: Request, name: str) -> Path:
    """The backup of that name, or a plain 404: only names this module writes are accepted, so
    no path can leave the backup folder."""
    if NAME.match(name) is None:
        raise ApiError(404, "Not found", "That backup does not exist.")
    path = _directory(request) / name
    if not path.is_file():
        raise ApiError(404, "Not found", "That backup does not exist.")
    return path


@router.get("/backups", response_model=list[BackupOut])
def list_backups(request: Request, _user: UserDep) -> list[BackupOut]:
    """The backups on the server, newest first (nightly ones and the copies taken before a
    migration or a restore)."""
    directory = _directory(request)
    if not directory.is_dir():
        return []
    found = [_out(p) for p in directory.glob("*.db") if NAME.match(p.name)]
    return sorted(found, key=lambda b: (b.created_at, b.name), reverse=True)


@router.post("/backups", response_model=BackupOut, status_code=201)
def make_backup(request: Request, body: BackupMakeIn, user: UserDep, db: DbDep) -> BackupOut:
    """A verified backup now."""
    settings = request.app.state.settings
    try:
        result = create_backup(
            settings.db_url,
            settings.backup_dir,
            extra_dir=settings.extra_backup_dir,
            include_secrets=body.include_secrets,
        )
    except BackupError as exc:
        raise ApiError(422, "Cannot back up", str(exc)) from exc
    write_audit(db, user.username, "backup", "create", diff={"file": result.path.name})
    return _out(result.path)


@router.get("/backups/{name}")
def download_backup(
    request: Request,
    name: str,
    background: BackgroundTasks,
    _user: UserDep,
    include_secrets: Annotated[bool, Query()] = False,
) -> FileResponse:
    """Download a backup. The stored API keys are left out unless `include_secrets=true`: a copy
    that leaves the server should not carry them."""
    path = _file(request, name)
    if include_secrets:
        return FileResponse(path, media_type="application/octet-stream", filename=name)
    folder = Path(tempfile.mkdtemp(prefix="folio-download-"))
    copy = folder / name
    stripped_copy(path, copy)
    background.add_task(shutil.rmtree, folder, ignore_errors=True)
    return FileResponse(copy, media_type="application/octet-stream", filename=name)


@router.delete("/backups/{name}", status_code=204)
def delete_backup(request: Request, name: str, user: UserDep, db: DbDep) -> None:
    path = _file(request, name)
    path.unlink()
    write_audit(db, user.username, "backup", "delete", diff={"file": name})


@router.post("/backups/upload", response_model=BackupOut, status_code=201)
def upload_backup(
    request: Request, user: UserDep, db: DbDep, file: Annotated[UploadFile, File()]
) -> BackupOut:
    """Put a backup file made elsewhere on the server, after checking that it is a sound Folio
    database. It is not restored until you say so."""
    directory = _directory(request)
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    stamp = now.strftime("%Y%m%d-%H%M%S")
    target, n = directory / f"upload-{stamp}.db", 1
    while target.exists():
        n += 1
        target = directory / f"upload-{stamp}-{n}.db"
    size = 0
    try:
        with target.open("wb") as out:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise ApiError(413, "Too large", "The file is larger than 512 MB.")
                out.write(chunk)
        verify_backup(target)
    except BackupError as exc:
        target.unlink(missing_ok=True)
        raise ApiError(422, "Not a Folio backup", str(exc)) from exc
    except ApiError:
        target.unlink(missing_ok=True)
        raise
    write_audit(db, user.username, "backup", "upload", diff={"file": target.name, "bytes": size})
    return _out(target)


@router.post("/restore", response_model=RestoreStartedOut, status_code=202)
def start_restore(
    request: Request, body: RestoreIn, background: BackgroundTasks, user: UserDep, db: DbDep
) -> RestoreStartedOut:
    """Stage a restore and restart. The current database is kept as a pre-restore copy; nobody
    is signed in afterwards, because the sessions come from the backup."""
    if body.confirm != CONFIRM:
        raise ApiError(422, "Not confirmed", f"Type {CONFIRM} to confirm the restore.")
    path = _file(request, body.name)
    settings = request.app.state.settings
    try:
        restore.stage(settings.db_url, path, body.name)
    except BackupError as exc:
        raise ApiError(422, "Cannot restore that backup", str(exc)) from exc
    write_audit(db, user.username, "backup", "restore", diff={"file": body.name})
    db.commit()  # the audit row is written before the database is replaced
    background.add_task(request.app.state.restart)
    return RestoreStartedOut(
        restarting=True,
        note="Folio is restarting with the backup. Sign in again in a minute.",
    )


@router.get("/restore", response_model=RestoreStatusOut)
def restore_status(request: Request, _user: UserDep) -> RestoreStatusOut:
    settings = request.app.state.settings
    data: dict[str, Any] | None = restore.last_result(settings.db_url)
    last = None
    if data is not None:
        last = RestoreResultOut(
            at=datetime.fromisoformat(str(data.get("at"))),
            source=str(data.get("from", "")),
            ok=bool(data.get("ok")),
            safety_copy=data.get("safety_copy"),
            error=data.get("error"),
        )
    return RestoreStatusOut(pending=restore.is_pending(settings.db_url), last=last)
