"""HTTP client: retries, call budget (FR-MD-10) and circuit breaker (NFR-05)."""

import threading
from datetime import date, timedelta

import httpx
import pytest

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.marketdata.base import BudgetExhausted, ProviderError, ProviderUnavailable
from folio.marketdata.budget import CircuitBreaker, UsageTracker
from folio.marketdata.http import check_status
from tests.marketdata_helpers import Scripted, client


@pytest.fixture
def usage(settings: Settings):  # type: ignore[no-untyped-def]
    factory = make_session_factory(make_engine(settings.db_url))
    limits = {"p": 0}
    tracker = UsageTracker(factory, lambda name: limits.get(name, 0))
    tracker.limits = limits  # type: ignore[attr-defined]
    return tracker


def ok(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": True})


def test_retries_server_errors_then_succeeds(usage: UsageTracker) -> None:
    answers = iter([503, 503, 200])
    scripted = Scripted(lambda r: httpx.Response(next(answers), json={"ok": True}))
    http = client("p", scripted, usage=usage)
    assert http.request("GET", "https://x.test/a").status_code == 200
    assert len(scripted.requests) == 3
    assert usage.usage_today() == {"p": 3}  # every attempt counts against the budget


def test_gives_up_after_three_attempts_with_a_plain_message(usage: UsageTracker) -> None:
    scripted = Scripted(lambda r: httpx.Response(504, text="gateway timeout"))
    http = client("p", scripted, usage=usage)
    with pytest.raises(ProviderError, match=r"p did not answer after 3 attempts \(HTTP 504\)"):
        http.request("GET", "https://x.test/a")
    assert len(scripted.requests) == 3


def test_rate_limit_and_network_errors_are_retried() -> None:
    steps = iter(["429", "network", "200"])

    def handler(request: httpx.Request) -> httpx.Response:
        step = next(steps)
        if step == "network":
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(int(step), json={})

    scripted = Scripted(handler)
    assert client("p", scripted).request("GET", "https://x.test/a").status_code == 200
    assert len(scripted.requests) == 3


def test_client_errors_are_returned_not_retried() -> None:
    scripted = Scripted(lambda r: httpx.Response(401, json={}))
    response = client("p", scripted).request("GET", "https://x.test/a")
    assert response.status_code == 401 and len(scripted.requests) == 1
    with pytest.raises(ProviderError, match="Check the API key"):
        check_status("p", response)


def test_sends_a_user_agent() -> None:
    scripted = Scripted(ok)
    client("p", scripted).request("GET", "https://x.test/a")
    assert "Folio" in scripted.requests[0].headers["user-agent"]


def test_budget_stops_calls_before_they_are_sent(usage: UsageTracker) -> None:
    usage.limits["p"] = 2  # type: ignore[attr-defined]
    scripted = Scripted(ok)
    http = client("p", scripted, usage=usage)
    http.request("GET", "https://x.test/a")
    http.request("GET", "https://x.test/a")
    with pytest.raises(BudgetExhausted, match="daily budget of 2 calls for p"):
        http.request("GET", "https://x.test/a")
    assert len(scripted.requests) == 2
    assert usage.usage_today() == {"p": 2}  # matches what the provider saw


def test_budget_is_per_provider_and_zero_means_unlimited(usage: UsageTracker) -> None:
    usage.limits["limited"] = 1  # type: ignore[attr-defined]
    usage.charge("limited")
    with pytest.raises(BudgetExhausted):
        usage.charge("limited")
    for _ in range(50):
        usage.charge("free")  # limit 0
    assert usage.usage_today() == {"limited": 1, "free": 50}


def test_budget_resets_on_a_new_day(settings: Settings) -> None:
    factory = make_session_factory(make_engine(settings.db_url))
    clock = {"day": date(2024, 3, 1)}
    tracker = UsageTracker(factory, lambda _: 1, today=lambda: clock["day"])
    tracker.charge("p")
    with pytest.raises(BudgetExhausted):
        tracker.charge("p")
    clock["day"] += timedelta(days=1)
    assert tracker.charge("p") == 1
    assert tracker.usage_today() == {"p": 1}


def test_budget_is_exact_under_concurrency(settings: Settings) -> None:
    factory = make_session_factory(make_engine(settings.db_url))
    tracker = UsageTracker(factory, lambda _: 10)
    results: list[bool] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            tracker.charge("p")
            outcome = True
        except BudgetExhausted:
            outcome = False
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker) for _ in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 10 and tracker.usage_today() == {"p": 10}


def test_circuit_breaker_pauses_a_provider_that_keeps_failing() -> None:
    now = {"t": 0.0}
    breaker = CircuitBreaker(threshold=3, cooldown=timedelta(minutes=15), clock=lambda: now["t"])
    healthy = {"up": False}
    scripted = Scripted(lambda r: httpx.Response(200 if healthy["up"] else 503, json={}))
    http = client("p", scripted, breaker=breaker, attempts=1)

    for _ in range(3):
        with pytest.raises(ProviderError):
            http.request("GET", "https://x.test/a")
    sent = len(scripted.requests)
    with pytest.raises(ProviderUnavailable, match="paused"):
        http.request("GET", "https://x.test/a")
    assert len(scripted.requests) == sent  # failed fast, nothing was sent

    now["t"] += 16 * 60  # cooldown over: one trial call is allowed
    healthy["up"] = True
    assert http.request("GET", "https://x.test/a").status_code == 200
    assert breaker.failures == 0 and not breaker.is_open
