"""The fictional demo portfolio and the backup, restore, job and seed commands."""

import sqlite3
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from folio.cli import app
from folio.config import Settings, get_settings
from folio.db import migrate
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import Account
from folio.db.models_analytics import Sleeve, WatchlistItem
from folio.db.models_ledger import (
    Instrument,
    JobRequest,
    LedgerTransaction,
    PortfolioSnapshot,
    Position,
    PriceBar,
)
from folio.db.models_strategy import Strategy
from folio.demo import DemoError, seed_demo
from folio.portfolio import Valuation
from tests.conftest import TEST_SECRET

D = Decimal
TODAY = date(2024, 6, 3)
runner = CliRunner()


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


# --- the demo portfolio ------------------------------------------------------------------------


def test_the_demo_portfolio_is_complete_and_fictional(db) -> None:  # type: ignore[no-untyped-def]
    counts = seed_demo(db, TODAY)
    db.commit()
    assert counts["instruments"] == 7 and counts["transactions"] >= 60
    assert counts["snapshots"] == (TODAY - date(2022, 6, 1)).days + 1  # one per calendar day
    instruments = db.scalars(select(Instrument)).all()
    assert len(instruments) == 7 and all(
        i.manual and i.isin is None for i in instruments
    )  # no real ISINs
    assert all(i.name.startswith("Demo ") for i in instruments)
    assert {b.source for b in db.scalars(select(PriceBar))} == {"demo"}  # no provider was involved
    assert db.query(JobRequest).count() == 0 and db.query(Position).count() >= 5

    point = Valuation.load(db).point(TODAY)
    assert point.value_eur > 0 and point.unvalued == 0 and point.net_contributions_eur > 0
    assert point.income_eur == D("24.80")  # two dividends of 12.40
    assert (
        db.scalars(select(PortfolioSnapshot).where(PortfolioSnapshot.date == TODAY))
        .one()
        .total_value_eur
        == point.value_eur
    )
    assert {t.source for t in db.scalars(select(LedgerTransaction))} == {"demo"}


def test_the_demo_shows_classification_sleeves_a_benchmark_and_a_watchlist(db) -> None:  # type: ignore[no-untyped-def]
    seed_demo(db, TODAY)
    db.commit()
    sleeves = {s.name: s for s in db.scalars(select(Sleeve))}
    assert sum(s.target_pct for s in sleeves.values() if s.target_pct) == D(100)
    classified = db.scalars(select(Instrument).where(Instrument.sleeve_id.is_not(None))).all()
    assert len(classified) == 6 and all(i.region and i.sector for i in classified)
    (benchmark,) = db.scalars(select(Instrument).where(Instrument.is_benchmark.is_(True)))
    assert benchmark.name == "Demo World Equity ETF"
    (item,) = db.scalars(select(WatchlistItem))
    watched = db.get(Instrument, item.instrument_id)
    assert watched is not None and watched.name == "Demo Dividend ETF"
    # watched, not held: it has prices but no transactions
    assert not db.scalars(
        select(LedgerTransaction).where(LedgerTransaction.instrument_id == watched.id)
    ).all()
    # an active strategy over the same sleeves leaves their targets as they were
    (strategy,) = db.scalars(select(Strategy)).all()
    assert (strategy.name, strategy.mode) == ("Demo strategy", "active")
    assert {s.name: s.target_pct for s in db.scalars(select(Sleeve))} == {
        "Core": 60,
        "Growth": 25,
        "Defensive": 15,
    }


def test_the_demo_is_deterministic(settings: Settings, db, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    seed_demo(db, TODAY)
    db.commit()
    other_url = f"sqlite:///{tmp_path / 'second.db'}"
    migrate.upgrade(other_url)
    with make_session_factory(make_engine(other_url))() as second:
        seed_demo(second, TODAY)
        second.commit()
        a, b = Valuation.load(db).point(TODAY), Valuation.load(second).point(TODAY)
        assert (a.value_eur, a.net_contributions_eur) == (b.value_eur, b.net_contributions_eur)
        assert second.query(LedgerTransaction).count() == db.query(LedgerTransaction).count()


def test_the_demo_will_not_mix_with_real_holdings(db) -> None:  # type: ignore[no-untyped-def]
    seed_demo(db, TODAY)
    db.commit()
    with pytest.raises(DemoError, match="without instruments or transactions"):
        seed_demo(db, TODAY)


def test_the_demo_reuses_the_account_made_by_the_setup_wizard(db) -> None:  # type: ignore[no-untyped-def]
    db.add(Account(name="My real account"))
    db.commit()
    seed_demo(db, TODAY)
    db.commit()
    assert [a.name for a in db.scalars(select(Account))] == ["My real account"]
    assert db.query(LedgerTransaction).count() > 0


# --- commands ----------------------------------------------------------------------------------


@pytest.fixture
def cli_env(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Settings]:
    monkeypatch.setenv("FOLIO_SECRET_KEY", TEST_SECRET)
    monkeypatch.setenv("FOLIO_DB_URL", settings.db_url)
    monkeypatch.setenv("FOLIO_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.delenv("FOLIO_EXTRA_BACKUP_DIR", raising=False)
    get_settings.cache_clear()
    yield settings
    get_settings.cache_clear()


def test_seed_demo_command(cli_env: Settings) -> None:
    refused = runner.invoke(app, ["seed"])
    assert refused.exit_code == 1 and "only `folio seed --demo`" in refused.output
    ok = runner.invoke(app, ["seed", "--demo"])
    assert ok.exit_code == 0, ok.output
    assert "7 instruments" in ok.output and "all fictional" in ok.output
    again = runner.invoke(app, ["seed", "--demo"])
    assert again.exit_code == 1 and "without instruments or transactions" in again.output


def test_backup_command(cli_env: Settings, tmp_path: Path) -> None:
    ok = runner.invoke(app, ["backup"])
    assert ok.exit_code == 0, ok.output
    assert "integrity ok" in ok.output
    files = list((tmp_path / "backups").glob("folio-*.db"))
    assert len(files) == 1
    bare = runner.invoke(app, ["backup", "--no-secrets", "--dir", str(tmp_path / "elsewhere")])
    assert bare.exit_code == 0 and len(list((tmp_path / "elsewhere").glob("*.db"))) == 1


def test_backup_command_explains_a_missing_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FOLIO_SECRET_KEY", TEST_SECRET)
    monkeypatch.setenv("FOLIO_DB_URL", f"sqlite:///{tmp_path / 'none.db'}")
    get_settings.cache_clear()
    try:
        r = runner.invoke(app, ["backup", "--dir", str(tmp_path / "b")])
    finally:
        get_settings.cache_clear()
    assert r.exit_code == 1 and "There is no database at" in r.output


def test_restore_command_asks_first_and_restores(cli_env: Settings, tmp_path: Path) -> None:
    runner.invoke(app, ["seed", "--demo"])
    runner.invoke(app, ["backup"])
    (backup,) = (tmp_path / "backups").glob("folio-*.db")
    engine = make_engine(cli_env.db_url)
    engine.dispose()
    declined = runner.invoke(app, ["restore", str(backup)], input="n\n")
    assert declined.exit_code == 1 and "Continue?" in declined.output
    assert not list((tmp_path / "backups").glob("pre-restore-*.db"))  # nothing happened
    ok = runner.invoke(app, ["restore", str(backup), "--yes"])
    assert ok.exit_code == 0, ok.output
    assert "saved as" in ok.output and "Start the web and worker again" in ok.output
    assert len(list((tmp_path / "backups").glob("pre-restore-*.db"))) == 1
    bad = runner.invoke(app, ["restore", str(tmp_path / "missing.db"), "--yes"])
    assert bad.exit_code == 1 and "does not exist" in bad.output


def test_run_job_command(cli_env: Settings) -> None:
    ok = runner.invoke(app, ["run-job", "fx"])
    assert ok.exit_code == 0 and "No foreign currency in use" in ok.output
    unknown = runner.invoke(app, ["run-job", "nope"])
    assert (
        unknown.exit_code == 1
        and "unknown job 'nope'" in unknown.output
        and "backfill" in unknown.output
    )
    missing = runner.invoke(app, ["run-job", "backfill"])
    assert missing.exit_code == 1 and "needs --param listing_id=" in missing.output
    failed = runner.invoke(app, ["run-job", "backfill", "-p", "listing_id=99999"])
    assert failed.exit_code == 1 and "no longer exists" in failed.output
    snap = runner.invoke(app, ["run-job", "snapshots", "-p", "from=2024-01-01"])
    assert snap.exit_code == 0 and "No transactions yet" in snap.output


def test_migrating_takes_a_safety_copy_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alembic import command

    url = f"sqlite:///{tmp_path / 'old.db'}"
    command.upgrade(migrate._config(url), "0002")
    con = sqlite3.connect(tmp_path / "old.db")
    con.execute(
        "INSERT INTO app_user (username, password_hash, created_at, updated_at) VALUES ('owner', 'x', '2024-01-01', '2024-01-01')"
    )
    con.commit()
    con.close()
    monkeypatch.setenv("FOLIO_SECRET_KEY", TEST_SECRET)
    monkeypatch.setenv("FOLIO_DB_URL", url)
    monkeypatch.setenv("FOLIO_BACKUP_DIR", str(tmp_path / "backups"))
    get_settings.cache_clear()
    try:
        r = runner.invoke(app, ["migrate"])
    finally:
        get_settings.cache_clear()
    assert r.exit_code == 0, r.output
    copies = list((tmp_path / "backups").glob("pre-migrate-*.db"))
    assert len(copies) == 1  # taken before the schema changed
    engine = make_engine(url)
    try:
        assert migrate.is_at_head(engine)
    finally:
        engine.dispose()
