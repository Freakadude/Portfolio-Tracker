"""Moving the background jobs to other times (FR-SY-09): the saved times are used by the
scheduler, validated in plain words, applied to a running worker, and shown with the next run."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models_ledger import JobRequest
from folio.jobs.cron import JOBS, parse_cron
from folio.jobs.scheduler import (
    apply_overrides,
    build_schedules,
    make_scheduler,
    process_job_requests,
)
from tests.conftest import PASSWORD, USERNAME
from tests.marketdata_helpers import make_ctx

AMSTERDAM = ZoneInfo("Europe/Amsterdam")


@pytest.fixture
def api(client: TestClient, owner: None) -> TestClient:
    client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return client


def test_a_saved_time_replaces_the_normal_one() -> None:
    normal = {s.job_id: s.trigger for s in build_schedules()}
    moved = {s.job_id: s.trigger for s in build_schedules({"snapshots": "30 21 * * mon-fri"})}
    friday = datetime(2025, 12, 19, 12, 0, tzinfo=AMSTERDAM)
    assert normal["snapshots"].get_next_fire_time(None, friday) == datetime(  # type: ignore[attr-defined]
        2025, 12, 19, 23, 0, tzinfo=AMSTERDAM
    )
    assert moved["snapshots"].get_next_fire_time(None, friday) == datetime(  # type: ignore[attr-defined]
        2025, 12, 19, 21, 30, tzinfo=AMSTERDAM
    )
    assert moved["fx"].get_next_fire_time(None, friday) == normal["fx"].get_next_fire_time(
        None, friday
    )  # type: ignore[attr-defined]  # the others are untouched
    after_friday = datetime(2025, 12, 19, 22, 0, tzinfo=AMSTERDAM)
    assert moved["snapshots"].get_next_fire_time(None, after_friday) == datetime(  # type: ignore[attr-defined]
        2025, 12, 22, 21, 30, tzinfo=AMSTERDAM
    )  # weekdays only: the next one is Monday


def test_every_listed_job_is_a_real_job_with_a_valid_normal_time() -> None:
    scheduled = {s.job_id for s in build_schedules()}
    assert {j.job_id for j in JOBS} <= scheduled
    for job in JOBS:
        parse_cron(job.cron, job.tz)  # the text shown as "normal" is itself valid


@pytest.mark.parametrize(
    ("text", "complaint"),
    [
        ("0 22 * *", "5 parts"),
        ("0 22 * * 1", "name"),
        ("99 22 * * *", "not a valid schedule"),
    ],
)
def test_a_bad_schedule_is_refused_in_plain_words(
    api: TestClient, text: str, complaint: str
) -> None:
    r = api.put("/api/v1/schedules/snapshots", json={"cron": text})
    assert r.status_code == 422 and complaint in r.json()["detail"]
    assert api.get("/api/v1/schedules").json()["items"][2]["changed"] is False  # nothing saved


def test_a_time_is_saved_shown_with_its_next_run_and_put_back(
    api: TestClient, settings: Settings
) -> None:
    listed = api.get("/api/v1/schedules").json()
    assert listed["timezone"] == "Europe/Amsterdam" and len(listed["items"]) == len(JOBS)
    assert any("XETR" in line for line in listed["fixed"])  # closing prices cannot be moved
    snapshots = next(i for i in listed["items"] if i["job_id"] == "snapshots")
    assert (snapshots["cron"], snapshots["changed"], snapshots["normal"]) == (
        "0 23 * * *",
        False,
        "every day at 23:00",
    )

    r = api.put("/api/v1/schedules/snapshots", json={"cron": "30  21 * * mon-fri"})
    assert r.status_code == 200, r.text
    assert r.json()["cron"] == "30 21 * * mon-fri" and r.json()["changed"] is True
    assert r.json()["next_run"] is not None
    with make_session_factory(make_engine(settings.db_url))() as db:  # the worker is asked
        assert db.scalars(select(JobRequest.job).where(JobRequest.job == "reschedule")).all() == [
            "reschedule"
        ]
    # writing the normal time (or null) puts it back
    back = api.put("/api/v1/schedules/snapshots", json={"cron": None}).json()
    assert back["changed"] is False and back["cron"] == "0 23 * * *"
    assert api.put("/api/v1/schedules/nope", json={"cron": "0 1 * * *"}).status_code == 404


def test_a_running_worker_moves_its_jobs_when_asked(api: TestClient, settings: Settings) -> None:
    ctx = make_ctx(settings, [])
    scheduler = make_scheduler(settings, ctx, persistent=False)
    scheduler.start(paused=True)
    try:
        api.put("/api/v1/schedules/gaps", json={"cron": "15 5 * * *"})
        process_job_requests(ctx, settings)  # picks up the "reschedule" request
        job = scheduler.get_job("gaps")
        assert job is not None
        moment = datetime(2025, 12, 19, 1, 0, tzinfo=UTC)
        fire = job.trigger.get_next_fire_time(None, moment)  # type: ignore[attr-defined]
        assert fire.astimezone(AMSTERDAM).strftime("%H:%M") == "05:15"
        assert apply_overrides(ctx) > 0
    finally:
        scheduler.shutdown()
