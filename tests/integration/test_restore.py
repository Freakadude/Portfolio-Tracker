"""Backups in the web app and restoring one (FR-SY-07): list, make, download without the API keys,
upload, and a restore that is staged, swapped in on the next start, and gives identical positions."""

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from folio import restore
from folio.backup import BackupError, create_backup
from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import Account, AuditLog
from folio.db.models_ledger import Position
from folio.ledger_service import TransactionIn, create_transaction
from tests.conftest import PASSWORD, USERNAME
from tests.marketdata_helpers import make_listing

D = Decimal
KEY = "sk-ant-api03-" + "k" * 40


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


@pytest.fixture
def exits() -> list[int]:
    return []


@pytest.fixture
def api(make_client: Callable[..., TestClient], owner: None, exits: list[int]) -> TestClient:
    c = make_client(restart=lambda: exits.append(1))
    c.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return c


def buy(db: Session, account_id: int, instrument_id: int, units: int, day: str) -> None:
    create_transaction(
        db,
        TransactionIn(
            account_id=account_id,
            instrument_id=instrument_id,
            type="buy",
            trade_date=datetime.fromisoformat(day).date(),
            quantity=D(units),
            price=D(100),
        ),
    )
    db.commit()


def positions(db: Session) -> list[tuple[int, int, Decimal, Decimal]]:
    db.expire_all()
    return [
        (p.account_id, p.instrument_id, p.quantity, p.cost_basis_eur)
        for p in db.scalars(select(Position).order_by(Position.id))
    ]


@pytest.fixture
def book(db: Session) -> dict[str, int]:
    instrument, _ = make_listing(db, ticker="F")
    account = Account(name="Degiro")
    db.add(account)
    db.flush()
    buy(db, account.id, instrument.id, 10, "2024-01-02")
    return {"account": account.id, "instrument": instrument.id}


def free(api: TestClient, db: Session) -> None:
    """Close every connection to the database file, as a stopped app has (a file in use cannot be
    swapped on Windows)."""
    db.close()
    db.get_bind().dispose()  # type: ignore[attr-defined]
    api.app.state.engine.dispose()  # type: ignore[attr-defined]


# --- listing, making, downloading, uploading ------------------------------------------------------


def test_the_backups_are_listed_newest_first_with_their_kind(
    api: TestClient, settings: Settings, book
) -> None:
    folder = Path(settings.backup_dir)
    folder.mkdir(parents=True, exist_ok=True)
    one = create_backup(
        settings.db_url, folder, now=datetime(2026, 10, 1, 3, 0, tzinfo=UTC), prefix="folio"
    )
    two = create_backup(
        settings.db_url, folder, now=datetime(2026, 10, 2, 3, 0, tzinfo=UTC), prefix="pre-migrate"
    )
    (folder / "notes.txt").write_text("not a backup")
    (folder / "folio-garbage.db").write_bytes(b"x")  # not a name this app writes
    listed = api.get("/api/v1/system/backups").json()
    assert [(b["name"], b["kind"]) for b in listed] == [
        (two.path.name, "pre-migrate"),
        (one.path.name, "folio"),
    ]
    assert listed[0]["size"] == two.path.stat().st_size and listed[0]["created_at"].startswith(
        "2026-10-02"
    )


def test_a_backup_made_now_is_verified_listed_and_audited(
    api: TestClient, settings: Settings, book, db: Session
) -> None:
    made = api.post("/api/v1/system/backups", json={})
    assert made.status_code == 201, made.text
    name = made.json()["name"]
    assert name.startswith("folio-") and (Path(settings.backup_dir) / name).is_file()
    assert [b["name"] for b in api.get("/api/v1/system/backups").json()] == [name]
    db.expire_all()
    row = db.scalars(select(AuditLog).where(AuditLog.entity == "backup")).one()
    assert (row.action, row.diff) == ("create", {"file": name})


def secrets_in(data: bytes, tmp_path: Path) -> int:
    path = tmp_path / "check.db"
    path.write_bytes(data)
    con = sqlite3.connect(path)
    try:
        return int(con.execute("SELECT COUNT(*) FROM secret").fetchone()[0])
    finally:
        con.close()


def test_a_download_leaves_out_the_api_keys_unless_asked(
    api: TestClient, settings: Settings, book, tmp_path: Path
) -> None:
    assert api.put("/api/v1/settings/agent", json={"anthropic_api_key": KEY}).status_code == 200
    name = api.post("/api/v1/system/backups", json={"include_secrets": True}).json()["name"]
    on_server = Path(settings.backup_dir) / name
    assert secrets_in(on_server.read_bytes(), tmp_path) == 1  # kept on the server with its keys
    plain = api.get(f"/api/v1/system/backups/{name}")
    assert plain.status_code == 200 and secrets_in(plain.content, tmp_path) == 0
    assert f'filename="{name}"' in plain.headers["content-disposition"]
    with_keys = api.get(f"/api/v1/system/backups/{name}", params={"include_secrets": "true"})
    assert secrets_in(with_keys.content, tmp_path) == 1
    assert secrets_in(on_server.read_bytes(), tmp_path) == 1  # the file itself was not touched


def test_only_names_this_app_writes_can_be_reached(api: TestClient, settings: Settings) -> None:
    for name in ("..%2Ffolio.db", "folio.db", "folio-2024.db", "notes.txt", "..%5Cx.db"):
        assert api.get(f"/api/v1/system/backups/{name}").status_code in (404, 422), name
        assert api.delete(f"/api/v1/system/backups/{name}").status_code in (404, 405, 422), name
    assert api.get("/api/v1/system/backups/folio-20240101-000000.db").status_code == 404


def test_an_uploaded_backup_is_checked_before_it_is_kept(
    api: TestClient, settings: Settings, book, tmp_path: Path
) -> None:
    source = create_backup(settings.db_url, tmp_path / "elsewhere").path
    ok = api.post(
        "/api/v1/system/backups/upload",
        files={"file": ("my-backup.db", source.read_bytes(), "application/octet-stream")},
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["kind"] == "upload" and ok.json()["name"].startswith("upload-")
    bad = api.post(
        "/api/v1/system/backups/upload",
        files={"file": ("junk.db", b"this is not a database", "application/octet-stream")},
    )
    assert bad.status_code == 422 and bad.json()["title"] == "Not a Folio backup"
    kept = sorted(p.name for p in Path(settings.backup_dir).glob("upload-*"))
    assert kept == [ok.json()["name"]]  # the refused file is not left behind


def test_a_backup_can_be_deleted(api: TestClient, settings: Settings, book) -> None:
    name = api.post("/api/v1/system/backups", json={}).json()["name"]
    assert api.delete(f"/api/v1/system/backups/{name}").status_code == 204
    assert api.get("/api/v1/system/backups").json() == []
    assert api.delete(f"/api/v1/system/backups/{name}").status_code == 404


# --- the restore ----------------------------------------------------------------------------------


def restore_via_api(api: TestClient, name: str, confirm: str = "RESTORE"):  # type: ignore[no-untyped-def]
    return api.post("/api/v1/system/restore", json={"name": name, "confirm": confirm})


def test_a_restore_needs_the_word_and_is_staged_then_applied_on_the_next_start(
    api: TestClient, settings: Settings, book, db: Session, exits: list[int]
) -> None:
    name = api.post("/api/v1/system/backups", json={}).json()["name"]
    before = positions(db)
    buy(db, book["account"], book["instrument"], 5, "2024-02-01")  # the state moves on
    assert positions(db) != before

    refused = restore_via_api(api, name, confirm="restore")
    assert refused.status_code == 422 and "Type RESTORE" in refused.json()["detail"]
    assert exits == [] and not restore.is_pending(settings.db_url)

    started = restore_via_api(api, name)
    assert started.status_code == 202 and started.json()["restarting"] is True
    assert exits == [1]  # the process is asked to stop once the answer is out
    assert restore.is_pending(settings.db_url)
    assert api.get("/api/v1/system/restore").json()["pending"] is True
    assert positions(db) != before  # nothing changed under the running app

    # the next start: before anything opens the database, the staged file is swapped in
    free(api, db)
    outcome = restore.apply_pending(settings.db_url, settings.backup_dir)
    assert outcome is not None and outcome["ok"] is True and outcome["from"] == name
    assert not restore.is_pending(settings.db_url)

    with make_session_factory(make_engine(settings.db_url))() as fresh:
        assert positions(fresh) == before  # identical positions
        assert fresh.scalars(select(Account)).one().name == "Degiro"
    safety = Path(settings.backup_dir) / outcome["safety_copy"]
    assert safety.name.startswith("pre-restore-") and safety.is_file()
    con = sqlite3.connect(safety)
    try:  # what was there before is kept: the later purchase is in the safety copy
        assert con.execute("SELECT COUNT(*) FROM ledger_transaction").fetchone()[0] == 2
    finally:
        con.close()


def test_the_outcome_is_shown_after_the_restart_and_the_worker_can_notice_it(
    api: TestClient, settings: Settings, book, db: Session
) -> None:
    name = api.post("/api/v1/system/backups", json={}).json()["name"]
    assert restore.result_stamp(settings.db_url) is None  # a worker started now remembers nothing
    restore_via_api(api, name)
    free(api, db)
    restore.apply_pending(settings.db_url, settings.backup_dir)
    assert restore.result_stamp(settings.db_url) is not None  # so the worker restarts too
    again = TestClient(__import__("folio.api.app", fromlist=["create_app"]).create_app(settings))
    again.get("/api/v1/auth/me")
    again.headers["X-CSRF-Token"] = again.cookies.get("folio_csrf") or ""
    again.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    status = again.get("/api/v1/system/restore").json()
    assert status["pending"] is False and status["last"]["ok"] is True
    assert status["last"]["source"] == name and status["last"]["safety_copy"].startswith(
        "pre-restore-"
    )


def test_a_backup_that_went_bad_after_staging_is_not_applied_and_changes_nothing(
    api: TestClient, settings: Settings, book, db: Session
) -> None:
    name = api.post("/api/v1/system/backups", json={}).json()["name"]
    restore_via_api(api, name)
    before = positions(db)
    restore.pending_path(settings.db_url).write_bytes(b"corrupted on the way")
    free(api, db)
    outcome = restore.apply_pending(settings.db_url, settings.backup_dir)
    assert outcome is not None and outcome["ok"] is False and "error" in outcome
    assert not restore.is_pending(settings.db_url)  # not tried again
    assert (
        restore.pending_path(settings.db_url)
        .with_name(restore.pending_path(settings.db_url).name + ".failed")
        .is_file()
    )
    with make_session_factory(make_engine(settings.db_url))() as fresh:
        assert positions(fresh) == before  # the database is as it was
    assert json.loads(restore.result_path(settings.db_url).read_text())["ok"] is False


def test_nothing_staged_means_nothing_happens(settings: Settings) -> None:
    assert restore.apply_pending(settings.db_url, settings.backup_dir) is None
    assert restore.last_result(settings.db_url) is None


def test_staging_refuses_a_file_that_is_not_a_backup(settings: Settings, tmp_path: Path) -> None:
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"nope")
    with pytest.raises(BackupError):
        restore.stage(settings.db_url, junk, "junk.db")
    assert not restore.is_pending(settings.db_url)


def test_restoring_an_unknown_backup_is_a_404_and_everything_needs_a_sign_in(
    api: TestClient, client: TestClient
) -> None:
    assert restore_via_api(api, "folio-20240101-000000.db").status_code == 404
    assert restore_via_api(api, "../../etc/passwd").status_code == 404
    other = client  # not signed in
    assert other.get("/api/v1/system/backups").status_code == 401
    assert other.post("/api/v1/system/backups", json={}).status_code == 401
    assert (
        other.post("/api/v1/system/restore", json={"name": "x", "confirm": "RESTORE"}).status_code
        == 401
    )
    assert other.get("/api/v1/system/restore").status_code == 401
