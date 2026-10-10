"""News sources, polite fetching, storage and the news job (FR-NW-01, FR-NW-02, FR-NW-03).

The ECB and Federal Reserve feeds are recorded from the live sites (2026-10-05); the EODHD news
response is derived from its documentation (tests/fixtures/providers/README.md)."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from tenacity import wait_none

from folio.api.routers import news as news_router
from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models_insight import NewsItem, NewsSource
from folio.db.models_ledger import JobRequest, ProviderCall
from folio.jobs import news as news_job_module
from folio.jobs.context import JobContext
from folio.jobs.news import news_job
from folio.marketdata.base import ProviderError
from folio.marketdata.budget import UsageTracker
from folio.marketdata.eodhd import EodhdProvider
from folio.marketdata.fallback import ProviderChain
from folio.news.fetch import Fetcher, RobotsDisallowed, backoff
from tests.conftest import PASSWORD, USERNAME
from tests.marketdata_helpers import Scripted, client, make_listing, respond

NEWS = Path(__file__).resolve().parents[1] / "fixtures" / "news"
ETAG = '"myra-60cdf498"'
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def feed(name: str) -> bytes:
    return (NEWS / name).read_bytes()


def web(request: httpx.Request) -> httpx.Response:
    """The ready-made feeds' sites, as recorded."""
    host, path = request.url.host, request.url.path
    if path == "/robots.txt":
        return httpx.Response(404)
    if host == "www.ecb.europa.eu" and path == "/rss/press.html":
        if request.headers.get("if-none-match") == ETAG:
            return httpx.Response(304)
        return httpx.Response(
            200,
            content=feed("ecb_press.xml"),
            headers={"content-type": "application/rss+xml", "etag": ETAG},
        )
    if host == "www.federalreserve.gov" and path == "/feeds/press_all.xml":
        return httpx.Response(
            200,
            content=feed("fed_press_all.xml"),
            headers={"content-type": "text/xml", "last-modified": "Fri, 02 Oct 2026 21:00:00 GMT"},
        )
    if host == "www.federalreserve.gov" and path == "/feeds/speeches_and_testimony.xml":
        return httpx.Response(200, content=feed("fed_speeches.xml"))
    if host == "www.federalregister.gov" and path == "/api/v1/documents.rss":
        return httpx.Response(200, content=feed("federal_register_bis.xml"))
    return httpx.Response(404)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def fetcher(scripted: Scripted, clock: Clock | None = None, now: datetime = NOW) -> Fetcher:
    clock = clock or Clock()
    return Fetcher(
        lambda domain: client("news", scripted),
        clock=lambda: now,
        monotonic=clock,
        sleep=clock.sleep,
    )


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


def job_ctx(
    settings: Settings,
    scripted: Scripted,
    now: datetime = NOW,
    eodhd: Scripted | None = None,
    eodhd_budget: int = 20,
) -> JobContext:
    factory = make_session_factory(make_engine(settings.db_url))
    usage = UsageTracker(factory, lambda p: eodhd_budget if p == "eodhd" else 0)
    return JobContext(
        session_factory=factory,
        chain_for=lambda db: ProviderChain([]),
        ecb_for=lambda db: None,  # type: ignore[arg-type, return-value]
        now=lambda: now,
        usage=usage,
        eodhd_for=lambda db: (
            None
            if eodhd is None
            else EodhdProvider(client("eodhd", eodhd, usage=usage), "fake-eodhd-key-1234")
        ),
        fetcher_for=lambda: fetcher(scripted, now=now),
    )


# --- the fetcher ----------------------------------------------------------------------------------


def test_a_304_answer_costs_no_parsing(
    settings: Settings, db, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    scripted = Scripted(web)
    first = news_job(job_ctx(settings, scripted))
    assert first.status == "ok"
    assert "ECB press releases: 15 new, 0 already stored" in first.log
    assert "Federal Reserve press releases: 8 new, 0 already stored" in first.log
    assert "EODHD news for your tickers: skipped, it needs an EODHD API key" in first.log
    assert "Federal Reserve speeches and testimony: 5 new, 0 already stored" in first.log
    assert "US export controls (BIS, Federal Register): 5 new, 0 already stored" in first.log
    assert "SEC filings for your holdings: skipped, it needs your contact email" in first.log
    assert "33 new items grouped into" in first.log  # then clustered and linked (FR-NW-04)
    source = db.scalar(select(NewsSource).where(NewsSource.name == "ECB press releases"))
    assert source.etag == ETAG and source.failures == 0

    parsed: list[int] = []
    real = news_job_module.parse_feed
    monkeypatch.setattr(news_job_module, "parse_feed", lambda *a: (parsed.append(1), real(*a))[1])
    later = news_job(job_ctx(settings, scripted, now=NOW + timedelta(minutes=61)))
    assert "ECB press releases: not modified" in later.log
    ecb = [r for r in scripted.requests if r.url.path == "/rss/press.html"][-1]
    assert ecb.headers["if-none-match"] == ETAG  # the earlier answer's ETag was sent back
    fed = [r for r in scripted.requests if r.url.path == "/feeds/press_all.xml"][-1]
    assert fed.headers["if-modified-since"] == "Fri, 02 Oct 2026 21:00:00 GMT"
    assert parsed == [1, 1]  # the two Fed feeds were parsed; the ECB's 304 was not
    assert "Federal Reserve press releases: 0 new, 8 already stored" in later.log


def test_a_source_is_only_fetched_when_it_is_due(settings: Settings) -> None:
    scripted = Scripted(web)
    news_job(job_ctx(settings, scripted))
    seen = len(scripted.requests)
    news_job(job_ctx(settings, scripted, now=NOW + timedelta(minutes=30)))  # polled hourly
    assert len(scripted.requests) == seen


def test_robots_txt_is_obeyed_and_cached_for_a_day() -> None:
    robots = (NEWS / "robots_example.txt").read_bytes()
    scripted = Scripted(
        lambda r: (
            httpx.Response(200, content=robots)
            if r.url.path == "/robots.txt"
            else httpx.Response(200, content=feed("ecb_press.xml"))
        )
    )
    f = fetcher(scripted)
    assert f.get("https://site.example/feeds/ok.xml").status == "ok"
    with pytest.raises(RobotsDisallowed, match="robots.txt does not allow"):
        f.get("https://site.example/feeds/blocked.xml")
    with pytest.raises(RobotsDisallowed):
        f.get("https://site.example/private/x.xml")
    asked = [r.url.path for r in scripted.requests]
    assert asked.count("/robots.txt") == 1  # read once for all three
    assert "/feeds/blocked.xml" not in asked and "/private/x.xml" not in asked  # never requested

    later = fetcher(scripted, now=NOW)
    later._robots = f._robots  # noqa: SLF001 - a day later the cache has expired
    later._clock = lambda: NOW + timedelta(hours=25)  # noqa: SLF001
    later.get("https://site.example/feeds/ok.xml")
    assert [r.url.path for r in scripted.requests].count("/robots.txt") == 2


def test_robots_txt_is_asked_on_the_feeds_own_port() -> None:
    scripted = Scripted(
        lambda r: (
            httpx.Response(404)
            if r.url.path == "/robots.txt"
            else httpx.Response(200, content=feed("ecb_press.xml"))
        )
    )
    assert fetcher(scripted).get("http://127.0.0.1:8766/ecb_press.xml").status == "ok"
    assert [str(r.url) for r in scripted.requests][0] == "http://127.0.0.1:8766/robots.txt"


def test_no_robots_txt_means_nothing_is_disallowed_but_a_failing_site_is_left_alone() -> None:
    absent = Scripted(
        lambda r: httpx.Response(404) if "robots" in r.url.path else respond("ecb_dfr.csv")
    )
    assert fetcher(absent).get("https://a.example/x.xml").status == "ok"
    failing = Scripted(lambda r: httpx.Response(503))
    with pytest.raises(ProviderError, match="did not answer|robots.txt"):
        fetcher(failing).get("https://b.example/x.xml")


def test_requests_to_one_site_are_spaced_but_different_sites_are_not_held_up() -> None:
    scripted = Scripted(web)
    clock = Clock()
    f = fetcher(scripted, clock)
    f.get("https://www.ecb.europa.eu/rss/press.html")  # robots.txt, then the feed: 10 s apart
    assert clock.slept == [10.0]
    f.get("https://www.federalreserve.gov/feeds/press_all.xml")  # another site: robots, feed
    assert clock.slept == [10.0, 10.0]
    clock.now += 60  # a minute later the next request to the ECB goes straight out
    f.get("https://www.ecb.europa.eu/rss/press.html")
    assert clock.slept == [10.0, 10.0]


def test_a_failing_source_backs_off_and_only_the_third_failure_fails_the_run(
    settings: Settings, db
) -> None:  # type: ignore[no-untyped-def]
    broken = Scripted(
        lambda r: httpx.Response(404) if "robots" in r.url.path else httpx.Response(503)
    )
    now = NOW
    results = []
    ran_at = []
    for _ in range(3):
        ran_at.append(now)
        results.append(news_job(job_ctx(settings, broken, now=now)))
        db.expire_all()
        ecb = db.scalar(select(NewsSource).where(NewsSource.name == "ECB press releases"))
        now = ecb.next_fetch_at.replace(tzinfo=UTC) + timedelta(minutes=1)
    assert [r.status for r in results] == ["ok", "ok", "failed"]  # quiet at first, loud at three
    assert ecb.failures == 3 and "did not answer after 3 attempts" in ecb.last_error
    # the waits double from the source's own hour: 1 h, 2 h, 4 h
    assert [backoff(60, n) for n in (1, 2, 3, 4)] == [
        timedelta(hours=1),
        timedelta(hours=2),
        timedelta(hours=4),
        timedelta(hours=8),
    ]
    assert backoff(60, 12) == timedelta(hours=24)  # never more than a day
    assert ecb.next_fetch_at.replace(tzinfo=UTC) - ran_at[-1] == timedelta(hours=4)

    recovered = news_job(job_ctx(settings, Scripted(web), now=now + timedelta(hours=5)))
    db.expire_all()
    ecb = db.scalar(select(NewsSource).where(NewsSource.name == "ECB press releases"))
    assert recovered.status == "ok" and ecb.failures == 0 and ecb.last_error is None


def test_a_missing_feed_says_so(settings: Settings, db) -> None:  # type: ignore[no-untyped-def]
    gone = Scripted(lambda r: httpx.Response(404))
    news_job(job_ctx(settings, gone))
    ecb = db.scalar(select(NewsSource).where(NewsSource.name == "ECB press releases"))
    assert "feed address was not found" in ecb.last_error


def test_a_page_that_is_not_a_feed_is_a_failure_with_advice(settings: Settings, db) -> None:  # type: ignore[no-untyped-def]
    page = Scripted(
        lambda r: (
            httpx.Response(404)
            if "robots" in r.url.path
            else httpx.Response(200, content=b"<html><body>Hi</body></html>")
        )
    )
    news_job(job_ctx(settings, page))
    ecb = db.scalar(select(NewsSource).where(NewsSource.name == "ECB press releases"))
    assert "does not return an RSS or Atom feed" in ecb.last_error and ecb.failures == 1


# --- what is stored (FR-NW-03) ----------------------------------------------------------------------


def test_only_headlines_summaries_links_and_metadata_are_stored(settings: Settings, db) -> None:  # type: ignore[no-untyped-def]
    news_job(job_ctx(settings, Scripted(web)))
    assert set(NewsItem.__table__.columns.keys()) == {
        "id", "created_at", "updated_at", "source_id", "canonical_url", "title", "summary",
        "published_at", "language", "content_hash", "symbols", "cluster_id",
    }  # fmt: skip  # no body, content or text column
    rows = db.scalars(select(NewsItem)).all()
    assert len(rows) == 33
    assert all(len(r.title) <= 300 and len(r.summary) <= 500 for r in rows)
    assert all(
        r.canonical_url.startswith("https://") and "//press" not in r.canonical_url for r in rows
    )
    assert len({r.canonical_url for r in rows}) == 33


# --- EODHD news -------------------------------------------------------------------------------------


def eodhd_setup(db) -> int:  # type: ignore[no-untyped-def]
    make_listing(db, ticker="ASML", mic="XAMS", symbols={"eodhd": "ASML.AS"})
    db.commit()
    from folio.news import service

    source = next(s for s in service.list_sources(db) if s.kind == "eodhd")
    db.commit()
    return source.id


def test_eodhd_news_is_stored_as_headlines_with_a_short_summary_and_its_tickers(
    settings: Settings, db
) -> None:  # type: ignore[no-untyped-def]
    source_id = eodhd_setup(db)
    answer = Scripted(lambda r: respond("eodhd_news.json"))
    result = news_job(job_ctx(settings, Scripted(web), eodhd=answer), source_id)
    assert result.status == "ok" and "2 new, 0 already stored" in result.log
    request = answer.requests[0]
    assert request.url.path == "/api/news" and request.url.params["s"] == "ASML.AS"
    assert db.scalar(select(ProviderCall.count).where(ProviderCall.provider == "eodhd")) == 5
    outlook = db.scalar(select(NewsItem).where(NewsItem.title.like("Chip equipment%")))
    assert len(outlook.summary) <= 500 and outlook.summary.endswith("…")
    assert "Lorem ipsum dolor sit amet" in outlook.summary and "laborum" not in outlook.summary
    assert outlook.canonical_url == "https://news.example/chip-outlook"
    assert outlook.symbols == ["ASML.AS", "SXR8.XETRA"]


def test_eodhd_news_leaves_the_budget_for_the_nightly_closes(settings: Settings, db) -> None:  # type: ignore[no-untyped-def]
    source_id = eodhd_setup(db)
    answer = Scripted(lambda r: respond("eodhd_news.json"))
    # one tracked listing keeps 1 + 5 calls for the closes; 8 left minus 5 for news is not enough
    result = news_job(job_ctx(settings, Scripted(web), eodhd=answer, eodhd_budget=8), source_id)
    assert "kept for the closes" in result.log and answer.requests == []
    with_room = news_job(job_ctx(settings, Scripted(web), eodhd=answer, eodhd_budget=20), source_id)
    assert "2 new" in with_room.log and len(answer.requests) == 1


# --- the API ----------------------------------------------------------------------------------------


@pytest.fixture
def api(
    make_client: Callable[..., TestClient], owner: None, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    monkeypatch.setattr(news_router, "PREVIEW_INTERVAL", 0.0)
    c = make_client(
        provider_transport=Scripted(web).transport, provider_http_options={"wait": wait_none()}
    )
    c.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return c


def test_the_ready_made_sources_come_once_and_stay_deleted(api: TestClient) -> None:
    listed = api.get("/api/v1/news/sources").json()
    assert [(s["name"], s["kind"]) for s in listed] == [
        ("ECB press releases", "rss"),
        ("Federal Reserve press releases", "rss"),
        ("EODHD news for your tickers", "eodhd"),
        ("Federal Reserve speeches and testimony", "rss"),
        ("US export controls (BIS, Federal Register)", "rss"),
        ("SEC filings for your holdings", "sec"),
        ("Nasdaq.com headlines for your shares", "rss"),
    ]
    fed = listed[1]
    assert fed["macro_series"] == ["DFF", "DFII10", "DTWEXBGS"] and fed["poll_minutes"] == 60
    assert listed[3]["macro_series"] == ["DFF", "DFII10", "DTWEXBGS"]  # the speeches too
    assert "{symbol}" in listed[6]["url"] and listed[6]["trust_weight"] == "0.5"
    assert api.delete(f"/api/v1/news/sources/{listed[2]['id']}").status_code == 204
    names = [s["name"] for s in api.get("/api/v1/news/sources").json()]
    assert "EODHD news for your tickers" not in names and len(names) == 6  # it does not come back


def test_sources_are_added_changed_and_checked(api: TestClient) -> None:
    body = {"name": "Issuer notices", "url": "https://issuer.example/feed.xml", "language": "nl",
            "trust_weight": "0.9", "poll_minutes": 120, "macro_series": ["DFF"]}  # fmt: skip
    made = api.post("/api/v1/news/sources", json=body)
    assert made.status_code == 201 and made.json()["language"] == "nl"
    source_id = made.json()["id"]
    changed = api.put(
        f"/api/v1/news/sources/{source_id}", json={**body, "poll_minutes": 30, "enabled": False}
    ).json()
    assert (changed["poll_minutes"], changed["enabled"]) == (30, False)
    for bad, message in (
        ({"url": "ftp://x"}, "must start with http"),
        ({"trust_weight": "5"}, "Trust must be between"),
        ({"poll_minutes": 5}, "every 15 minutes"),
        ({"name": " "}, "Give the source a name"),
        ({"language": "1"}, "language is a code"),
    ):
        refused = api.post("/api/v1/news/sources", json={**body, **bad})
        assert refused.status_code == 422 and message in refused.json()["detail"]
    assert api.put("/api/v1/news/sources/9999", json=body).status_code == 404
    audit = api.get("/api/v1/audit", params={"entity": "news_source"}).json()
    assert {e["action"] for e in audit["items"]} >= {"create", "update"}


def test_a_feed_is_previewed_with_its_last_ten_items_before_it_is_saved(
    api: TestClient, db
) -> None:  # type: ignore[no-untyped-def]
    shown = api.post(
        "/api/v1/news/sources/preview", json={"url": "https://www.ecb.europa.eu/rss/press.html"}
    )
    assert shown.status_code == 200
    out = shown.json()
    assert (len(out["items"]), out["total"]) == (10, 15)
    assert out["items"][0]["title"].startswith("Philip R. Lane")  # the newest first
    published = [i["published"] for i in out["items"]]
    assert published == sorted(published, reverse=True)
    assert db.scalar(select(func.count()).select_from(NewsItem)) == 0  # a preview stores nothing


def test_a_preview_of_something_that_is_no_feed_or_is_forbidden_is_explained(
    api: TestClient,
) -> None:
    def preview(url: str) -> httpx.Response:
        return api.post("/api/v1/news/sources/preview", json={"url": url})

    assert "must start with http" in preview("not a url").json()["detail"]
    assert "not found" in preview("https://www.ecb.europa.eu/nothing").json()["detail"]


def test_fetch_now_queues_the_news_job_for_the_worker(api: TestClient, db) -> None:  # type: ignore[no-untyped-def]
    first = api.get("/api/v1/news/sources").json()[0]["id"]
    assert api.post(f"/api/v1/news/sources/{first}/fetch").status_code == 202
    queued = db.scalars(select(JobRequest).where(JobRequest.job == "news")).all()
    assert [q.params for q in queued] == [{"source_id": first}]
    assert api.post("/api/v1/news/sources/9999/fetch").status_code == 404


def test_a_failing_source_is_listed_on_the_system_page(api: TestClient, settings: Settings) -> None:
    broken = Scripted(lambda r: httpx.Response(404))
    news_job(job_ctx(settings, broken))
    info = api.get("/api/v1/system/info").json()
    assert "ECB press releases" in info["failing_news_sources"]
    listed = api.get("/api/v1/news/sources").json()
    assert listed[0]["failures"] == 1 and "not found" in listed[0]["last_error"]
