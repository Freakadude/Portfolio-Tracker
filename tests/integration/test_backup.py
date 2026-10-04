"""Backups, retention, restore (FR-SY-06, FR-SY-07)."""

import sqlite3
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import select

from folio.backup import (
    BackupError,
    backup_before_migration,
    create_backup,
    prune,
    restore_backup,
    sqlite_path,
    verify_backup,
)
from folio.config import Settings
from folio.db import migrate
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import Account
from folio.db.models_ledger import Position
from folio.ledger_service import TransactionIn, create_transaction
from folio.security.secrets import SecretStore
from tests.conftest import TEST_SECRET
from tests.marketdata_helpers import make_listing

D = Decimal
NOW = datetime(2024, 3, 1, 3, 0, tzinfo=UTC)
FAKE_KEY = "eodhd-SENTINEL-key-123456"  # gitleaks:allow - an invented value for the tests


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


@pytest.fixture
def backups(tmp_path: Path) -> Path:
    return tmp_path / "backups"


def populate(db) -> int:  # type: ignore[no-untyped-def]
    """The golden FIFO scenario: 5 units left with a cost of 600.5, realized 346.5."""
    instrument, _ = make_listing(db)
    account = Account(name="Degiro")
    db.add(account)
    db.flush()
    for day, qty, price, fees in (
        ("2024-01-02", "10", "100", "1"),
        ("2024-02-01", "10", "120", "1"),
    ):
        create_transaction(db, TransactionIn(account_id=account.id, instrument_id=instrument.id, type="buy", trade_date=date.fromisoformat(day), quantity=D(qty), price=D(price), fees=D(fees)))  # fmt: skip
    create_transaction(db, TransactionIn(account_id=account.id, instrument_id=instrument.id, type="sell", trade_date=date(2024, 2, 20), quantity=D(15), price=D(130), fees=D(2)))  # fmt: skip
    db.commit()
    return account.id  # type: ignore[no-any-return]


def positions(url: str) -> list[tuple[int, int, Decimal, Decimal, Decimal]]:
    engine = make_engine(url)
    try:
        with make_session_factory(engine)() as session:
            rows = session.scalars(select(Position).order_by(Position.id))
            return [
                (p.account_id, p.instrument_id, p.quantity, p.cost_basis_eur, p.realized_pnl_eur)
                for p in rows
            ]
    finally:
        engine.dispose()  # a held connection keeps the file open, which would block a restore


def at_head(url: str) -> bool:
    engine = make_engine(url)
    try:
        return migrate.is_at_head(engine)
    finally:
        engine.dispose()


# --- creating a backup ---------------------------------------------------------------------


def test_a_backup_is_a_verified_copy_of_the_whole_database(
    settings: Settings, db, backups: Path
) -> None:  # type: ignore[no-untyped-def]
    populate(db)
    result = create_backup(settings.db_url, backups, now=NOW)
    assert result.path.parent == backups and result.path.name == "folio-20240301-030000.db"
    assert result.size == result.path.stat().st_size > 0
    con = sqlite3.connect(result.path)
    try:
        assert con.execute("PRAGMA integrity_check").fetchall() == [("ok",)]  # opens and is sound
        assert con.execute("SELECT count(*) FROM ledger_transaction").fetchone() == (3,)
    finally:
        con.close()
    verify_backup(result.path)
    assert positions(f"sqlite:///{result.path}") == positions(settings.db_url) != []


def test_the_backup_is_taken_while_the_app_has_the_database_open(
    settings: Settings, db, backups: Path
) -> None:  # type: ignore[no-untyped-def]
    populate(db)  # this session is still open on the database
    reader = make_session_factory(make_engine(settings.db_url))()
    reader.scalars(select(Position)).all()  # a second connection reading
    create_backup(settings.db_url, backups, now=NOW)
    reader.close()


def test_two_backups_in_the_same_second_do_not_collide(
    settings: Settings, db, backups: Path
) -> None:  # type: ignore[no-untyped-def]
    populate(db)
    a = create_backup(settings.db_url, backups, now=NOW).path
    b = create_backup(settings.db_url, backups, now=NOW).path
    assert a != b and a.exists() and b.exists()


def test_secrets_can_be_left_out_of_a_backup(settings: Settings, db, backups: Path) -> None:  # type: ignore[no-untyped-def]
    SecretStore(db, TEST_SECRET).set("providers.eodhd_api_key", FAKE_KEY)
    db.commit()
    full = create_backup(settings.db_url, backups, now=NOW).path
    bare = create_backup(
        settings.db_url, backups, now=NOW + timedelta(hours=1), include_secrets=False
    ).path

    def secrets_in(path: Path) -> int:
        con = sqlite3.connect(path)
        try:
            return int(con.execute("SELECT count(*) FROM secret").fetchone()[0])
        finally:
            con.close()

    assert secrets_in(full) == 1 and secrets_in(bare) == 0
    assert FAKE_KEY.encode() not in full.read_bytes()  # stored encrypted either way
    db.expire_all()
    assert (
        SecretStore(db, TEST_SECRET).get("providers.eodhd_api_key") == FAKE_KEY
    )  # the live data is untouched


def test_a_second_copy_goes_to_the_extra_folder(
    settings: Settings, db, backups: Path, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    populate(db)
    nas = tmp_path / "nas"
    result = create_backup(settings.db_url, backups, extra_dir=nas, now=NOW)
    assert result.copied_to == nas / result.path.name
    assert result.copied_to.read_bytes() == result.path.read_bytes()


def test_backups_need_a_file_database(tmp_path: Path) -> None:
    with pytest.raises(BackupError, match="file-based SQLite"):
        sqlite_path("postgresql://u:p@host/db")
    with pytest.raises(BackupError, match="file-based SQLite"):
        sqlite_path("sqlite://")
    with pytest.raises(BackupError, match="no database at"):
        create_backup(f"sqlite:///{tmp_path / 'absent.db'}", tmp_path / "b")


# --- retention ---------------------------------------------------------------------------


def touch(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(b"x")
    return path


def test_retention_keeps_14_daily_and_8_weekly_copies(backups: Path) -> None:
    start = date(2024, 1, 1)
    for i in range(91):  # 1 January to 31 March, one a day
        touch(backups, f"folio-{(start + timedelta(days=i)).strftime('%Y%m%d')}-030000.db")
    bystander = touch(backups, "notes.txt")
    other = touch(backups, "folio-latest.db")
    removed = prune(backups)
    kept = sorted(p.name for p in backups.glob("folio-2*.db"))
    daily = [f"folio-202403{d}-030000.db" for d in range(18, 32)]  # the 14 newest
    weekly = [  # the newest of each of the 8 weeks before them (Sundays)
        "folio-20240317-030000.db", "folio-20240310-030000.db", "folio-20240303-030000.db",
        "folio-20240225-030000.db", "folio-20240218-030000.db", "folio-20240211-030000.db",
        "folio-20240204-030000.db", "folio-20240128-030000.db",
    ]  # fmt: skip
    assert kept == sorted(daily + weekly) and len(kept) == 22
    assert len(removed) == 91 - 22
    assert bystander.exists() and other.exists()  # files that are not backups are never touched


def test_retention_with_few_backups_keeps_them_all(backups: Path) -> None:
    for d in (1, 2, 3):
        touch(backups, f"folio-2024030{d}-030000.db")
    assert prune(backups) == [] and len(list(backups.glob("folio-*.db"))) == 3


def test_safety_copies_are_limited_separately(backups: Path) -> None:
    for d in range(1, 9):
        touch(backups, f"pre-migrate-2024030{d}-030000.db")
        touch(backups, f"pre-restore-2024030{d}-030000.db")
    touch(backups, "folio-20240301-030000.db")
    prune(backups)
    assert (
        len(list(backups.glob("pre-migrate-*.db"))) == 5
        and len(list(backups.glob("pre-restore-*.db"))) == 5
    )
    assert (backups / "pre-migrate-20240308-030000.db").exists()  # the newest are the ones kept
    assert (backups / "folio-20240301-030000.db").exists()


def test_creating_a_backup_applies_retention(settings: Settings, db, backups: Path) -> None:  # type: ignore[no-untyped-def]
    populate(db)
    for i in range(20):
        touch(
            backups, f"folio-{(date(2024, 1, 1) + timedelta(days=i)).strftime('%Y%m%d')}-030000.db"
        )
    result = create_backup(settings.db_url, backups, now=datetime(2024, 1, 21, 3, 0, tzinfo=UTC))
    names = {p.name for p in backups.glob("folio-*.db")}
    assert len(result.pruned) == 6  # 1 to 6 January: older copies of a week already represented
    assert (
        len(names) == 15 and "folio-20240107-030000.db" in names
    )  # 14 newest + that week's newest
    assert result.path.name in names


# --- restore -----------------------------------------------------------------------------


def test_restoring_a_backup_recreates_identical_positions(
    settings: Settings, db, backups: Path
) -> None:  # type: ignore[no-untyped-def]
    populate(db)
    expected = positions(settings.db_url)
    assert expected and expected[0][2:] == (D(5), D("600.5"), D("346.5"))
    backup = create_backup(settings.db_url, backups, now=NOW).path

    # disaster: the working data is lost
    db.close()
    db.get_bind().dispose()  # the app is stopped: nothing holds the file open
    con = sqlite3.connect(sqlite_path(settings.db_url))
    con.executescript("DELETE FROM lot_match; DELETE FROM lot; DELETE FROM position;")
    con.commit()
    con.close()
    assert positions(settings.db_url) == []

    result = restore_backup(backup, settings.db_url, backups, now=NOW + timedelta(hours=1))
    assert positions(settings.db_url) == expected  # identical, to the last digit
    assert result.safety_copy is not None and result.safety_copy.name.startswith("pre-restore-")
    assert positions(f"sqlite:///{result.safety_copy}") == []  # the damaged state was kept aside
    assert at_head(settings.db_url)


def test_restoring_into_a_missing_database(
    settings: Settings, db, backups: Path, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    populate(db)
    expected = positions(settings.db_url)
    backup = create_backup(settings.db_url, backups, now=NOW).path
    fresh_url = f"sqlite:///{tmp_path / 'new' / 'folio.db'}"
    result = restore_backup(backup, fresh_url, backups)
    assert result.safety_copy is None  # nothing existed to protect
    assert positions(fresh_url) == expected


def test_restore_refuses_files_that_are_not_good_backups(
    settings: Settings, tmp_path: Path, backups: Path
) -> None:
    garbage = tmp_path / "garbage.db"
    garbage.write_bytes(b"this is not a database at all" * 100)
    with pytest.raises(BackupError, match="not a valid database file"):
        restore_backup(garbage, settings.db_url, backups)
    other = tmp_path / "other.db"
    con = sqlite3.connect(other)
    con.execute("CREATE TABLE t (x)")
    con.commit()
    con.close()
    with pytest.raises(BackupError, match="not a Folio database"):
        restore_backup(other, settings.db_url, backups)
    with pytest.raises(BackupError, match="does not exist"):
        restore_backup(tmp_path / "missing.db", settings.db_url, backups)
    assert list(backups.glob("*")) == []  # a refused restore leaves no stray safety copies


def test_a_backup_that_does_not_verify_is_not_kept(
    settings: Settings, db, backups: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    populate(db)

    def fail(path: Path) -> None:
        raise BackupError("failed the integrity check")

    monkeypatch.setattr("folio.backup.verify_backup", fail)
    with pytest.raises(BackupError, match="integrity check"):
        create_backup(settings.db_url, backups, now=NOW)
    assert list(backups.glob("*.db")) == []


def old_database(tmp_path: Path, revision: str) -> str:
    """A database as an older version of Folio left it, with an owner account."""
    url = f"sqlite:///{tmp_path / 'old.db'}"
    command.upgrade(migrate._config(url), revision)
    con = sqlite3.connect(tmp_path / "old.db")
    con.execute(
        "INSERT INTO app_user (username, password_hash, created_at, updated_at) VALUES ('owner', 'x', '2024-01-01', '2024-01-01')"
    )
    con.commit()
    con.close()
    return url


def test_restoring_an_older_backup_migrates_it_forward(
    settings: Settings, tmp_path: Path, backups: Path
) -> None:
    url = old_database(tmp_path, "0002")
    assert not at_head(url)
    backup = create_backup(url, backups, now=NOW).path
    target_url = f"sqlite:///{tmp_path / 'target.db'}"
    restore_backup(backup, target_url, backups)
    assert at_head(target_url)
    columns = {
        row[1]
        for row in sqlite3.connect(tmp_path / "target.db").execute(
            "PRAGMA table_info(portfolio_snapshot)"
        )
    }
    assert {
        "income_eur",
        "costs_eur",
        "unvalued_positions",
    } <= columns  # the newer schema is in place


def test_a_safety_copy_is_taken_before_a_migration_changes_the_schema(
    tmp_path: Path, backups: Path
) -> None:
    url = old_database(tmp_path, "0002")
    copy = backup_before_migration(url, backups)
    assert copy is not None and copy.name.startswith("pre-migrate-")
    verify_backup(copy)
    migrate.upgrade(url)
    assert backup_before_migration(url, backups) is None  # already current: nothing to protect


def test_no_safety_copy_for_a_new_or_missing_database(tmp_path: Path, backups: Path) -> None:
    assert backup_before_migration(f"sqlite:///{tmp_path / 'nothing.db'}", backups) is None
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()  # a new empty file, no tables yet
    assert backup_before_migration(f"sqlite:///{empty}", backups) is None
    assert backup_before_migration("postgresql://u:p@h/db", backups) is None
    assert not backups.exists() or list(backups.glob("*")) == []
