"""The worker's schedule and the job-request queue (FR-MD-02, NFR-05)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import Account
from folio.db.models_ledger import JobRequest, JobRun, PortfolioSnapshot, PriceBar
from folio.jobs import scheduler as sched
from folio.jobs.market import eod_job
from folio.jobs.scheduler import (
    MISFIRE_GRACE_SECONDS,
    build_schedules,
    make_scheduler,
    process_job_requests,
)
from folio.ledger_service import TransactionIn, create_transaction
from folio.marketdata.fake import FakeProvider
from tests.marketdata_helpers import bars_for, make_ctx, make_listing

D = Decimal
BERLIN, NEW_YORK, LONDON, AMSTERDAM = (
    ZoneInfo(z) for z in ("Europe/Berlin", "America/New_York", "Europe/London", "Europe/Amsterdam")
)


def triggers() -> dict[str, object]:
    return {s.job_id: s.trigger for s in build_schedules()}


def next_after(job_id: str, moment: datetime) -> datetime:
    return triggers()[job_id].get_next_fire_time(None, moment)  # type: ignore[attr-defined, no-any-return]


# --- when things run ---------------------------------------------------------------------------


def test_every_job_is_scheduled() -> None:
    ids = set(triggers())
    assert {"fx", "gaps", "snapshots", "backup", "actions"} <= ids
    assert {f"eod-{mic}" for mic in ("XETR", "XAMS", "XLON", "XNYS", "XSWX")} <= ids


def test_closes_are_fetched_two_hours_after_each_exchange_closes() -> None:
    friday_night = datetime(2025, 12, 19, 20, 0, tzinfo=BERLIN)
    assert next_after("eod-XETR", friday_night) == datetime(
        2025, 12, 22, 19, 30, tzinfo=BERLIN
    )  # Xetra closes 17:30
    assert next_after("eod-XAMS", friday_night) == datetime(2025, 12, 22, 19, 30, tzinfo=AMSTERDAM)
    assert next_after("eod-XLON", datetime(2025, 12, 19, 20, 0, tzinfo=LONDON)) == datetime(
        2025, 12, 22, 18, 30, tzinfo=LONDON
    )
    assert next_after("eod-XNYS", datetime(2025, 7, 7, 19, 0, tzinfo=NEW_YORK)) == datetime(
        2025, 7, 8, 18, 0, tzinfo=NEW_YORK
    )
    before_close = datetime(2025, 12, 22, 12, 0, tzinfo=BERLIN)
    assert next_after("eod-XETR", before_close) == datetime(
        2025, 12, 22, 19, 30, tzinfo=BERLIN
    )  # the same day
    saturday = datetime(2025, 12, 20, 9, 0, tzinfo=BERLIN)
    assert next_after("eod-XETR", saturday).date() == date(2025, 12, 22)  # never on a weekend


def test_the_other_jobs_run_at_their_hours() -> None:
    monday = datetime(2025, 1, 6, 17, 0, tzinfo=AMSTERDAM)
    assert next_after("fx", monday) == datetime(
        2025, 1, 7, 16, 30, tzinfo=AMSTERDAM
    )  # after the ECB publishes
    assert next_after("snapshots", monday) == datetime(2025, 1, 6, 23, 0, tzinfo=AMSTERDAM)
    assert next_after("gaps", monday) == datetime(2025, 1, 6, 22, 0, tzinfo=AMSTERDAM)
    assert next_after("backup", monday) == datetime(2025, 1, 7, 3, 0, tzinfo=AMSTERDAM)
    assert next_after("actions", monday) == datetime(
        2025, 1, 12, 9, 0, tzinfo=AMSTERDAM
    )  # weekly, on Sunday


def test_christmas_day_is_a_trading_holiday_the_job_itself_skips(settings: Settings) -> None:
    # the schedule still fires on weekdays; the job asks the exchange calendar (FR-MD-02)
    fire = next_after("eod-XETR", datetime(2025, 12, 24, 20, 0, tzinfo=BERLIN))
    assert fire == datetime(2025, 12, 25, 19, 30, tzinfo=BERLIN)
    provider = FakeProvider(name="p", error=AssertionError("no fetch on a holiday"))
    result = eod_job(make_ctx(settings, [provider]), "XETR", day=date(2025, 12, 25))
    assert provider.calls == [] and "closed" in result.log


# --- registration, persistence ----------------------------------------------------------------


def test_jobs_are_registered_by_importable_name_with_catch_up_settings(settings: Settings) -> None:
    scheduler = make_scheduler(settings, make_ctx(settings, []), persistent=False)
    scheduler.start(paused=True)  # a job gets its defaults when the scheduler starts
    try:
        jobs = {job.id: job for job in scheduler.get_jobs()}
    finally:
        scheduler.shutdown()
    assert set(jobs) == {s.job_id for s in build_schedules()} | {"job-requests"}
    eod = jobs["eod-XETR"]
    assert eod.func_ref == "folio.jobs.scheduler:run_eod" and eod.args == ("XETR",)
    assert jobs["snapshots"].func_ref == "folio.jobs.scheduler:run_snapshots"
    assert jobs["job-requests"].trigger.interval.total_seconds() == 5  # type: ignore[attr-defined]
    for job_id in ("eod-XETR", "fx", "backup"):
        job = jobs[job_id]
        assert job.coalesce is True and job.max_instances == 1  # a missed run happens once
        assert job.misfire_grace_time == MISFIRE_GRACE_SECONDS == 6 * 3600


def test_the_schedule_survives_a_restart_without_duplicates(settings: Settings) -> None:
    ctx = make_ctx(settings, [])
    for _ in range(2):  # the worker starts twice
        scheduler = make_scheduler(settings, ctx, persistent=True)
        scheduler.start(paused=True)
        scheduler.shutdown()
    reader = BackgroundScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=settings.db_url, tablename="apscheduler_jobs")}
    )
    reader.start(paused=True)
    try:
        jobs = reader.get_jobs()
        ids = [job.id for job in jobs]
        assert sorted(ids) == sorted({s.job_id for s in build_schedules()} | {"job-requests"})
        assert len(ids) == len(set(ids))  # persisted once, however often the worker started
        assert all(job.next_run_time is not None for job in jobs)
    finally:
        reader.shutdown()


def test_scheduled_functions_need_the_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sched, "_runtime", None)
    with pytest.raises(RuntimeError, match="runtime is not set"):
        sched.run_fx()


def test_scheduled_functions_run_the_jobs(settings: Settings) -> None:
    ctx = make_ctx(settings, [], now=datetime(2024, 1, 15, 12, tzinfo=UTC))
    sched.set_runtime(ctx, settings)
    sched.run_snapshots()
    sched.run_eod("XETR")  # nothing is tracked there: no run record at all
    with make_session_factory(make_engine(settings.db_url))() as db:
        assert [r.job for r in db.scalars(select(JobRun))] == ["snapshots"]


def test_exchanges_without_tracked_listings_leave_no_trace(settings: Settings) -> None:
    ctx = make_ctx(settings, [])
    skipped = eod_job(ctx, "XETR", day=date(2024, 1, 3), only_if_tracked=True)
    assert (skipped.status, skipped.run_id) == (
        "skipped",
        0,
    ) and "No tracked listings" in skipped.log
    with make_session_factory(make_engine(settings.db_url))() as db:
        assert db.query(JobRun).count() == 0
        make_listing(db)
        db.commit()
    ran = eod_job(ctx, "XETR", day=date(2024, 1, 3), only_if_tracked=True)
    assert ran.run_id > 0  # now that something is tracked, it runs (and records itself)


# --- the job-request queue ---------------------------------------------------------------------


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


def request(db, job: str, **params: object) -> int:  # type: ignore[no-untyped-def]
    row = JobRequest(job=job, params=params)
    db.add(row)
    db.commit()
    return row.id  # type: ignore[no-any-return]


def outcome(db, request_id: int) -> JobRequest:  # type: ignore[no-untyped-def]
    db.expire_all()
    return db.get(JobRequest, request_id)  # type: ignore[return-value]


def test_requests_are_processed_oldest_first_and_recorded(settings: Settings, db) -> None:  # type: ignore[no-untyped-def]
    _, listing = make_listing(db)
    provider = FakeProvider(
        name="p", bars={listing.id: bars_for("XETR", date(2023, 1, 2), date(2024, 1, 12))}
    )
    ctx = make_ctx(settings, [provider], now=datetime(2024, 1, 12, 18, tzinfo=UTC))
    first = request(db, "backfill", listing_id=listing.id)
    second = request(db, "snapshots", **{"from": "2024-01-02"})
    assert process_job_requests(ctx, settings) == 2
    done = outcome(db, first)
    assert done.status == "done" and done.error is None
    assert (
        done.picked_up_at is not None
        and done.finished_at is not None
        and done.picked_up_at <= done.finished_at
    )
    assert outcome(db, second).status == "done"
    assert db.query(PriceBar).count() > 100  # the backfill really ran
    assert [r.job for r in db.scalars(select(JobRun).order_by(JobRun.id))] == [
        "backfill",
        "snapshots",
    ]  # in order
    assert process_job_requests(ctx, settings) == 0  # nothing pending any more


def test_a_failing_request_is_marked_failed_and_the_queue_continues(settings: Settings, db) -> None:  # type: ignore[no-untyped-def]
    ctx = make_ctx(settings, [], now=datetime(2024, 1, 12, 18, tzinfo=UTC))
    unknown = request(db, "make-coffee")
    missing = request(db, "backfill", listing_id=99999)  # the job reports it as an error
    broken = request(db, "backfill", listing_id="not-a-number")  # the handler itself raises
    fine = request(db, "fx")
    assert process_job_requests(ctx, settings) == 4
    assert (
        outcome(db, unknown).status == "failed"
        and "Unknown job 'make-coffee'" in outcome(db, unknown).error
    )  # type: ignore[operator]
    assert (
        outcome(db, missing).status == "failed" and "no longer exists" in outcome(db, missing).error
    )  # type: ignore[operator]
    assert outcome(db, broken).status == "failed" and "ValueError" in outcome(db, broken).error  # type: ignore[operator]
    assert outcome(db, fine).status == "done"  # one bad request did not stop the rest


def test_only_pending_requests_are_picked_up(settings: Settings, db) -> None:  # type: ignore[no-untyped-def]
    ctx = make_ctx(settings, [])
    done = request(db, "fx")
    row = outcome(db, done)
    row.status = "done"
    db.commit()
    running = request(db, "fx")
    outcome(db, running).status = "running"
    db.commit()
    assert process_job_requests(ctx, settings) == 0
    assert db.query(JobRun).count() == 0


def test_a_backup_can_be_requested(settings: Settings, db, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    cfg = settings.model_copy(
        update={"backup_dir": str(tmp_path / "bk"), "extra_backup_dir": str(tmp_path / "nas")}
    )
    ctx = make_ctx(cfg, [], now=datetime(2024, 3, 1, 3, tzinfo=UTC))
    rid = request(db, "backup")
    assert process_job_requests(ctx, cfg) == 1
    assert outcome(db, rid).status == "done"
    assert [p.name for p in (tmp_path / "bk").glob("*.db")] == ["folio-20240301-030000.db"]
    assert [p.name for p in (tmp_path / "nas").glob("*.db")] == ["folio-20240301-030000.db"]


def test_a_backup_that_cannot_be_made_is_reported(settings: Settings, db, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    cfg = settings.model_copy(update={"db_url": "sqlite://", "backup_dir": str(tmp_path / "bk")})
    result = sched.backup_job(make_ctx(settings, []), cfg)
    assert result.status == "failed" and "file-based SQLite" in result.log


def test_requests_for_ledger_edits_rebuild_snapshots(settings: Settings, db) -> None:  # type: ignore[no-untyped-def]
    """The loop FR-TX-06 relies on: a ledger edit queues a request, the worker redoes snapshots."""
    instrument, listing = make_listing(db)
    for bar in bars_for("XETR", date(2024, 1, 1), date(2024, 1, 12)):
        db.add(PriceBar(listing_id=listing.id, date=bar.date, close=bar.close, source="x"))
    account = Account(name="A")
    db.add(account)
    db.flush()
    create_transaction(db, TransactionIn(account_id=account.id, instrument_id=instrument.id, type="buy", trade_date=date(2024, 1, 2), quantity=D(10), price=D(100)))  # fmt: skip
    db.commit()
    ctx = make_ctx(settings, [], now=datetime(2024, 1, 12, 18, tzinfo=UTC))
    assert process_job_requests(ctx, settings) == 1  # the request the transaction queued
    db.expire_all()
    first = db.scalars(select(PortfolioSnapshot).order_by(PortfolioSnapshot.date)).first()
    assert first is not None and first.date == date(2024, 1, 2) and first.total_value_eur == 1000
