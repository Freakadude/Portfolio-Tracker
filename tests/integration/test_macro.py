"""Macro series from FRED and the ECB, the macro job, its rules and the chart widget (FR-MD-08)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models_analytics import MacroPoint, MacroSeries
from folio.db.models_ledger import JobRequest
from folio.db.models_strategy import Signal
from folio.jobs.context import JobContext
from folio.jobs.macro import macro_job
from folio.marketdata.base import ProviderError
from folio.marketdata.ecb import EcbRates
from folio.marketdata.fallback import ProviderChain
from folio.marketdata.fred import FredSeries
from folio.strategies import service
from tests.conftest import PASSWORD, USERNAME
from tests.marketdata_helpers import Scripted, client, respond

D = Decimal
NOW = datetime(2024, 6, 14, 6, tzinfo=UTC)


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


def fred_answers(request: httpx.Request) -> httpx.Response:
    series = request.url.params["series_id"]
    return respond({"DFII10": "fred_dfii10.json", "DTWEXBGS": "fred_dtwexbgs.json"}.get(series, "fred_error_series.json"),
                   200 if series in ("DFII10", "DTWEXBGS") else 400)  # fmt: skip


def ecb_answers(request: httpx.Request) -> httpx.Response:
    return respond("ecb_dfr.csv", content_type="text/csv")


def job_ctx(settings: Settings, fred: Scripted | None, ecb: Scripted) -> JobContext:
    return JobContext(
        session_factory=make_session_factory(make_engine(settings.db_url)),
        chain_for=lambda db: ProviderChain([]),
        ecb_for=lambda db: EcbRates(client("ecb", ecb)),
        fred_for=lambda db: (
            None if fred is None else FredSeries(client("fred", fred), "fake-fred-key-1234")
        ),
        now=lambda: NOW,
    )


# --- adapters -----------------------------------------------------------------------------------


def test_fred_observations_skip_missing_days_and_send_the_documented_query() -> None:
    scripted = Scripted(fred_answers)
    points = FredSeries(client("fred", scripted), "fake-fred-key-1234").observations(
        "DFII10", date(2024, 5, 1)
    )
    assert points[0] == (date(2024, 5, 1), D("1.80")) and points[-1][1] == D("2.34")
    assert date(2024, 5, 27) not in {d for d, _ in points}  # FRED's "." for a holiday
    params = scripted.requests[0].url.params
    assert (params["series_id"], params["file_type"], params["observation_start"]) == (
        "DFII10",
        "json",
        "2024-05-01",
    )


def test_fred_errors_are_explained_without_repeating_the_key() -> None:
    bad_key = Scripted(lambda r: respond("fred_error_400.json", 400))
    with pytest.raises(ProviderError, match="the API key is not valid") as exc:
        FredSeries(client("fred", bad_key), "fake-fred-key-1234").observations(
            "DFII10", date(2024, 5, 1)
        )
    assert "fake-fred-key" not in str(exc.value)
    unknown = Scripted(fred_answers)
    with pytest.raises(ProviderError, match="series does not exist"):
        FredSeries(client("fred", unknown), "k" * 32).observations("NOPE", date(2024, 5, 1))


def test_the_ecb_adapter_reads_any_series_key() -> None:
    scripted = Scripted(ecb_answers)
    points = EcbRates(client("ecb", scripted)).series("FM/D.U2.EUR.4F.KR.DFR.LEV", date(2024, 6, 8))
    assert points[0] == (date(2024, 6, 8), D(4))
    assert scripted.requests[0].url.path.endswith("/FM/D.U2.EUR.4F.KR.DFR.LEV")
    with pytest.raises(ProviderError, match="not an ECB series key"):
        EcbRates(client("ecb", scripted)).series("/etc/passwd", date(2024, 6, 8))


# --- the job ------------------------------------------------------------------------------------


def test_the_macro_job_stores_every_series_once(settings: Settings, db) -> None:  # type: ignore[no-untyped-def]
    ctx = job_ctx(settings, Scripted(fred_answers), Scripted(ecb_answers))
    first = macro_job(ctx)
    assert first.status == "failed"  # DFF is not in the fixtures: FRED says it does not exist
    assert "US 10-year real yield: 32 new or changed" in first.log
    assert "Fed funds rate: FRED refused the request" in first.log
    names = {s.code: s.name for s in db.scalars(select(MacroSeries))}
    assert names["DFII10"] == "US 10-year real yield" and "ECB_DFR" in names
    again = macro_job(ctx)
    assert "US 10-year real yield: 0 new or changed" in again.log  # idempotent


def test_without_a_fred_key_the_fred_series_are_skipped_and_said_so(settings: Settings, db) -> None:  # type: ignore[no-untyped-def]
    result = macro_job(job_ctx(settings, None, Scripted(ecb_answers)))
    assert result.status == "ok"
    assert "Skipped without a FRED API key: US 10-year real yield" in result.log
    assert {s.code for s in db.scalars(select(MacroSeries))} == {"ECB_DFR"}


def test_a_strategy_series_is_fetched_and_its_rule_fires_after_the_job(
    settings: Settings, db
) -> None:  # type: ignore[no-untyped-def]
    yaml = """\
strategy:
  name: Macro watch
  macro_series:
    REAL_YIELD: { source: fred, code: DFII10 }
  sleeves: [{ id: gold }]
  rules:
    - { id: ry, type: macro_threshold, series: REAL_YIELD, change_bp: 30, window_days: 30, applies_to: [gold], severity: low }
"""
    created = service.create(db, service.read_input(yaml, None))
    service.set_mode(db, created, "active")
    db.commit()
    macro_job(job_ctx(settings, Scripted(fred_answers), Scripted(ecb_answers)))
    db.expire_all()
    (signal,) = db.scalars(select(Signal)).all()
    assert (signal.rule_id, signal.subject, signal.severity) == ("ry", "REAL_YIELD", "low")
    assert "moved 37 bp in 30 days" in signal.payload["title"] and "concerns gold" in signal.message


# --- API and widget -----------------------------------------------------------------------------


@pytest.fixture
def api(client: TestClient, owner: None) -> TestClient:  # noqa: F811 - the conftest client
    client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return client


def widget(api: TestClient, config: dict[str, Any]) -> Any:
    body = {
        "as_of": "2024-06-14",
        "filters": {},
        "requests": [{"key": "m", "type": "macro_overlay", "config": config}],
    }
    r = api.post("/api/v1/widgets/data", json=body)
    assert r.status_code == 200, r.text
    return r.json()["results"]["m"]


def test_the_macro_widget_shows_the_real_yield_and_the_dollar_in_separate_panes(
    api: TestClient, settings: Settings, db
) -> None:  # type: ignore[no-untyped-def]
    assert widget(api, {})["data"]["empty"] is True
    macro_job(job_ctx(settings, Scripted(fred_answers), Scripted(ecb_answers)))
    data = widget(api, {"period": "MAX"})["data"]
    assert [p["name"] for p in data["panes"]] == [
        "US 10-year real yield",
        "Trade-weighted US dollar (broad)",
    ]
    assert data["panes"][0]["points"][-1] == {"date": "2024-06-14", "value": "2.34"}
    assert data["panes"][1]["unit"] == "index"
    chosen = widget(api, {"period": "MAX", "series_code": "ECB_DFR"})["data"]
    assert [p["code"] for p in chosen["panes"]] == ["ECB_DFR"]
    assert widget(api, {"series_code": "NOPE"})["error"] is not None


def test_the_series_list_and_fetch_now(api: TestClient, settings: Settings, db) -> None:  # type: ignore[no-untyped-def]
    macro_job(job_ctx(settings, Scripted(fred_answers), Scripted(ecb_answers)))
    listed = {s["code"]: s for s in api.get("/api/v1/macro/series").json()}
    assert listed["DFII10"]["last_value"] == "2.34" and listed["DFII10"]["configured"] is True
    assert listed["DFF"]["points"] == 0  # on the list, nothing stored yet
    assert db.scalar(select(MacroPoint.id)) is not None
    assert api.post("/api/v1/macro/refresh").status_code == 202
    api.post("/api/v1/macro/refresh")
    assert len(db.scalars(select(JobRequest).where(JobRequest.job == "macro")).all()) == 1
