"""The LLM client, cost tracking and the budget (FR-AG-04, FR-AG-09), against a scripted
Anthropic API: the official SDK builds the requests and reads the answers; only the network is
replaced (tests/agent_helpers.py)."""

import datetime as dt
from collections.abc import Callable
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from folio.agent import budget
from folio.agent.llm import LlmError, system_blocks, web_search_tool, with_cache
from folio.agent.runs import finish_run, metered_create, start_run
from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models_insight import AgentRun
from folio.db.models_ledger import FxRate
from folio.db.models_strategy import Notification, Signal
from folio.security.secrets import SecretStore
from folio.settings_schema import AgentSettings
from folio.settings_store import save_section
from tests.agent_helpers import KEY, ScriptedLlm, error, message, text, tool_use
from tests.conftest import PASSWORD, TEST_SECRET, USERNAME

D = Decimal
NOW = dt.datetime(2026, 10, 14, 17, 30, tzinfo=dt.UTC)  # 19:30 in Amsterdam
AMS = ZoneInfo("Europe/Amsterdam")
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer"],
    "properties": {"answer": {"type": "string"}},
}


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


def cfg(**over: object) -> AgentSettings:
    return AgentSettings(**over)  # type: ignore[arg-type]


# --- the client -------------------------------------------------------------------------------


def test_a_request_is_built_with_caching_tools_and_structured_output() -> None:
    scripted = ScriptedLlm(message(text('{"answer": "ok"}')))
    tools = with_cache(
        [
            {
                "name": "get_x",
                "description": "x",
                "input_schema": {"type": "object"},
                "strict": True,
            },
            web_search_tool(["ecb.europa.eu", "federalreserve.gov"], 3),
        ]
    )
    reply = scripted.client().create(
        model="claude-sonnet-5-5",
        system=system_blocks("Rules", "Strategy"),
        messages=[{"role": "user", "content": "Go"}],
        max_tokens=500,
        tools=tools,
        output_schema=SCHEMA,
    )
    sent = scripted.requests[0]
    assert (sent["model"], sent["max_tokens"]) == ("claude-sonnet-5-5", 500)
    assert [b.get("cache_control") for b in sent["system"]] == [None, {"type": "ephemeral"}]
    assert sent["tools"][0]["strict"] is True and "cache_control" not in sent["tools"][0]
    assert sent["tools"][1]["cache_control"] == {"type": "ephemeral"}  # on the last tool
    search = sent["tools"][1]
    assert (search["type"], search["name"], search["max_uses"]) == (
        "web_search_20250305",
        "web_search",
        3,
    )
    assert search["allowed_domains"] == ["ecb.europa.eu", "federalreserve.gov"]
    assert sent["output_config"] == {"format": {"type": "json_schema", "schema": SCHEMA}}
    assert scripted.headers[0]["x-api-key"] == KEY
    assert reply.text == '{"answer": "ok"}' and reply.stop_reason == "end_turn"


def test_usage_tool_calls_and_searches_are_read_from_the_answer() -> None:
    answer = message(
        {"type": "server_tool_use", "id": "srv_1", "name": "web_search", "input": {"query": "ecb rates"}},
        {
            "type": "web_search_tool_result",
            "tool_use_id": "srv_1",
            "content": [
                {"type": "web_search_result", "url": "https://ecb.europa.eu/a", "title": "A",
                 "encrypted_content": "x", "page_age": None},
            ],
        },
        text("Rates are unchanged."),
        tool_use("get_positions", "toolu_9", filter="all"),
        stop="tool_use",
        input_tokens=1200,
        output_tokens=300,
        cache_read=8000,
        cache_write=500,
        searches=1,
    )  # fmt: skip
    reply = (
        ScriptedLlm(answer)
        .client()
        .create(
            model="claude-sonnet-5-5",
            system=[],
            messages=[{"role": "user", "content": "Go"}],
            max_tokens=100,
        )
    )
    assert reply.text == "Rates are unchanged." and reply.stop_reason == "tool_use"
    assert [(t.id, t.name, t.input) for t in reply.tool_uses] == [
        ("toolu_9", "get_positions", {"filter": "all"})
    ]
    assert (reply.usage.input_tokens, reply.usage.output_tokens) == (1200, 300)
    assert (reply.usage.cache_read_tokens, reply.usage.cache_write_tokens) == (8000, 500)
    assert reply.usage.web_searches == 1
    assert reply.searches == [{"query": "ecb rates", "urls": ["https://ecb.europa.eu/a"]}]
    assert [b["type"] for b in reply.content] == [
        "server_tool_use",
        "web_search_tool_result",
        "text",
        "tool_use",
    ]  # the blocks go back verbatim on the next turn


@pytest.mark.parametrize(
    ("status", "kind", "api_type", "fragment"),
    [
        (401, "auth", "authentication_error", "refused the API key"),
        (403, "auth", "permission_error", "may not use that model"),
        (429, "rate_limit", "rate_limit_error", "limiting requests"),
        (529, "overloaded", "overloaded_error", r"had a problem \(HTTP 529\)"),
        (500, "overloaded", "api_error", r"had a problem \(HTTP 500\)"),
    ],
)
def test_failures_are_explained_without_the_key(
    status: int, kind: str, api_type: str, fragment: str
) -> None:
    scripted = ScriptedLlm(error(status, api_type, "boom " + KEY))
    with pytest.raises(LlmError, match=fragment) as caught:
        scripted.client().create(
            model="m", system=[], messages=[{"role": "user", "content": "x"}], max_tokens=10
        )
    assert caught.value.kind == kind and KEY not in str(caught.value)


def test_an_empty_account_and_a_bad_request_are_told_apart() -> None:
    credit = ScriptedLlm(
        error(400, "invalid_request_error", "Your credit balance is too low to access the API.")
    )
    with pytest.raises(LlmError, match="no credit left") as caught:
        credit.client().create(
            model="m", system=[], messages=[{"role": "user", "content": "x"}], max_tokens=10
        )
    assert caught.value.kind == "billing"
    bad = ScriptedLlm(error(400, "invalid_request_error", "max_tokens: must be positive"))
    with pytest.raises(LlmError, match="rejected the request: max_tokens: must be positive"):
        bad.client().create(
            model="m", system=[], messages=[{"role": "user", "content": "x"}], max_tokens=10
        )


def test_a_network_failure_is_reported_as_one() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route")

    from folio.agent.llm import LlmClient

    client = LlmClient(KEY, transport=httpx2.MockTransport(refuse), max_retries=0)
    with pytest.raises(LlmError, match="could not be reached") as caught:
        client.create(
            model="m", system=[], messages=[{"role": "user", "content": "x"}], max_tokens=10
        )
    assert caught.value.kind == "network"


# --- cost and budget --------------------------------------------------------------------------


def run_with(db, cost: str, run_type: str = "daily_review", when: dt.datetime = NOW) -> AgentRun:  # type: ignore[no-untyped-def]
    run = start_run(db, "test", run_type, "claude-sonnet-5-5", "system@1+abc", when)
    run.cost_eur = D(cost)
    db.commit()
    return run


def test_the_month_is_the_calendar_month_in_the_owners_timezone() -> None:
    late = dt.datetime(2026, 9, 30, 22, 30, tzinfo=dt.UTC)  # already 1 October in Amsterdam
    assert budget.month_start(late, AMS) == dt.datetime(2026, 9, 30, 22, 0, tzinfo=dt.UTC)
    assert budget.month_start(NOW, AMS) == dt.datetime(2026, 9, 30, 22, 0, tzinfo=dt.UTC)
    assert budget.day_start(NOW, AMS) == dt.datetime(2026, 10, 13, 22, 0, tzinfo=dt.UTC)


def test_what_the_month_has_cost_is_summed_per_kind_of_run(db) -> None:  # type: ignore[no-untyped-def]
    run_with(db, "1.25")
    run_with(db, "0.50", "news_assess")
    run_with(db, "0.25", "test")
    run_with(db, "9.00", when=dt.datetime(2026, 9, 29, 12, tzinfo=dt.UTC))  # last month
    state = budget.standing(db, cfg(), NOW, AMS)
    assert (state.month, state.spent_eur, state.news_spent_eur) == ("2026-10", D("2.00"), D("0.50"))
    assert (state.runs_this_month, state.runs_today) == (1, 1)  # news steps and tests are no runs
    assert state.remaining_eur == D("3.00")


def test_a_call_that_could_pass_the_budget_is_refused_before_it_is_made(db) -> None:  # type: ignore[no-untyped-def]
    run_with(db, "4.50")
    check = lambda usd: budget.check_call(  # noqa: E731
        db, cfg(), NOW, AMS, run_type="daily_review", worst_case_usd_amount=D(usd)
    )
    check("0.50")  # 4.50 + about 0.45 EUR fits in 5
    with pytest.raises(budget.BudgetExceeded, match="2026-10 is used up") as caught:
        check("0.60")  # 0.545 EUR more would pass 5.00
    assert caught.value.kind == "month"


def test_news_triage_may_only_use_its_share_of_the_budget(db) -> None:  # type: ignore[no-untyped-def]
    run_with(db, "1.40", "news_assess")
    call = lambda run_type: budget.check_call(  # noqa: E731
        db, cfg(), NOW, AMS, run_type=run_type, worst_case_usd_amount=D("0.22")
    )
    with pytest.raises(budget.BudgetExceeded, match="News triage has used its share") as caught:
        call("news_link")  # 1.40 + 0.20 > the 1.50 share
    assert caught.value.kind == "news_share"
    call("daily_review")  # the agent is not held to the news share


def test_the_daily_run_cap_counts_only_new_agent_runs(db) -> None:  # type: ignore[no-untyped-def]
    for _ in range(2):
        run_with(db, "0.01")
    small = cfg(daily_run_cap=2)
    budget.check_call(db, small, NOW, AMS, run_type="daily_review", worst_case_usd_amount=D("0.01"))
    with pytest.raises(budget.BudgetExceeded, match="2 runs for today") as caught:
        budget.check_call(
            db,
            small,
            NOW,
            AMS,
            run_type="daily_review",
            worst_case_usd_amount=D("0.01"),
            new_run=True,
        )
    assert caught.value.kind == "daily_runs"
    budget.check_call(
        db, small, NOW, AMS, run_type="news_assess", worst_case_usd_amount=D("0.01"), new_run=True
    )


def test_a_model_without_a_price_cannot_be_used(db) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(budget.BudgetExceeded, match="no price for claude-future") as caught:
        budget.price_for(cfg(), "claude-future")
    assert caught.value.kind == "price"


def test_cost_is_converted_at_the_latest_ecb_rate_or_the_fallback(db) -> None:  # type: ignore[no-untyped-def]
    usage = (
        ScriptedLlm(message(text("x"), input_tokens=100_000, output_tokens=10_000))
        .client()
        .create(
            model="claude-sonnet-5-5",
            system=[],
            messages=[{"role": "user", "content": "x"}],
            max_tokens=10,
        )
        .usage
    )
    run = start_run(db, "t", "daily_review", "claude-sonnet-5-5", "", NOW)
    fallback = budget.charge(db, run, cfg(), usage, "claude-sonnet-5-5", NOW.date())
    assert fallback == D("0.409091")  # $0.45 at the fallback rate of 1.10
    db.add(FxRate(date=NOW.date() - dt.timedelta(days=2), currency="USD", rate_per_eur=D("1.25")))
    db.flush()
    again = budget.charge(db, run, cfg(), usage, "claude-sonnet-5-5", NOW.date())
    assert again == D("0.36")  # the ECB's last rate, from two days before
    assert run.cost_eur == fallback + again and run.input_tokens == 200_000


def test_when_the_budget_stops_a_run_one_notice_is_made_a_month(db) -> None:  # type: ignore[no-untyped-def]
    exc = budget.BudgetExceeded("month", "The AI budget for 2026-10 is used up.")
    assert budget.stop_notice(db, exc, NOW, AMS, "daily_review") is True
    assert budget.stop_notice(db, exc, NOW + dt.timedelta(hours=5), AMS, "daily_review") is False
    db.commit()
    (item,) = db.scalars(select(Notification).where(Notification.source == "system")).all()
    assert (item.severity, item.link) == ("medium", "/system")
    assert "this month's budget is used up" in item.title and "Rules, alerts" in item.body
    assert "€" not in item.push_body and "EUR" not in item.push_body
    assert (
        budget.stop_notice(db, budget.BudgetExceeded("price", "x"), NOW, AMS, "daily_review")
        is False
    )


def test_a_stop_with_a_critical_signal_open_is_critical(db) -> None:  # type: ignore[no-untyped-def]
    db.add(
        Signal(rule_id="r", rule_type="drawdown", subject="x", severity="critical", message="m",
               ts=NOW - dt.timedelta(days=1), dedup_key="r:x", shadow=False)
    )  # fmt: skip
    db.commit()
    budget.stop_notice(db, budget.BudgetExceeded("month", "used up"), NOW, AMS, "daily_review")
    assert (
        db.scalar(select(Notification.severity).where(Notification.source == "system"))
        == "critical"
    )


# --- metered calls ----------------------------------------------------------------------------


def test_a_metered_call_is_charged_and_the_database_is_committed_before_the_call(db) -> None:  # type: ignore[no-untyped-def]
    committed: list[bool] = []

    def peek(body):  # type: ignore[no-untyped-def]
        committed.append(bool(db.in_transaction()))
        return message(text("hello"), input_tokens=2000, output_tokens=500)

    scripted = ScriptedLlm(handler=peek)
    run = start_run(db, "daily", "daily_review", "claude-sonnet-5-5", "system@1+abc", NOW)
    reply = metered_create(
        db, scripted.client(), cfg(), AMS, NOW, run, model="claude-sonnet-5-5",
        system=system_blocks("Rules"), messages=[{"role": "user", "content": "Go"}], max_tokens=1000,
    )  # fmt: skip
    assert reply.text == "hello" and committed == [False]  # no write lock held during the call
    assert (run.input_tokens, run.output_tokens) == (2000, 500)
    assert run.cost_eur == D("0.012273")  # $0.0135 at the fallback 1.10, in euro
    finish_run(db, run, NOW)
    assert run.status == "ok" and run.finished_at == NOW


def test_a_refused_call_never_reaches_the_api(db) -> None:  # type: ignore[no-untyped-def]
    run_with(db, "4.99")
    scripted = ScriptedLlm(message(text("never")))
    run = start_run(db, "daily", "daily_review", "claude-sonnet-5-5", "", NOW)
    with pytest.raises(budget.BudgetExceeded):
        metered_create(
            db, scripted.client(), cfg(), AMS, NOW, run, model="claude-sonnet-5-5",
            system=[], messages=[{"role": "user", "content": "Go"}], max_tokens=4000,
        )  # fmt: skip
    assert scripted.requests == []


def test_a_run_stops_at_its_token_cap(db) -> None:  # type: ignore[no-untyped-def]
    scripted = ScriptedLlm(
        message(text("a"), input_tokens=900, output_tokens=200), message(text("b"))
    )
    small = cfg(per_run_token_cap=1000)
    run = start_run(db, "daily", "daily_review", "claude-sonnet-5-5", "", NOW)
    ask = lambda: metered_create(  # noqa: E731
        db, scripted.client(), small, AMS, NOW, run, model="claude-sonnet-5-5",
        system=[], messages=[{"role": "user", "content": "Go"}], max_tokens=100,
    )  # fmt: skip
    ask()
    with pytest.raises(budget.BudgetExceeded, match="limit of 1000 tokens") as caught:
        ask()
    assert caught.value.kind == "run_tokens" and len(scripted.requests) == 1


# --- the API ------------------------------------------------------------------------------------


@pytest.fixture
def api(make_client: Callable[..., TestClient], owner: None) -> Callable[..., TestClient]:
    def build(scripted: ScriptedLlm | None = None) -> TestClient:
        c = make_client(llm_transport=None if scripted is None else scripted.transport)
        c.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
        return c

    return build


def save_key(db, key: str = KEY, **over: object) -> None:  # type: ignore[no-untyped-def]
    save_section(db, SecretStore(db, TEST_SECRET), "agent", cfg(anthropic_api_key=key, **over))
    db.commit()


def test_usage_shows_the_month_against_the_budget(api, db) -> None:  # type: ignore[no-untyped-def]
    c = api()
    run_with(db, "1.00", when=dt.datetime.now(dt.UTC))
    out = c.get("/api/v1/agent/usage").json()
    assert (out["spent_eur"], out["budget_eur"], out["remaining_eur"]) == (
        "1.00",
        "5",
        "4.00",
    )
    assert (out["enabled"], out["key_set"], out["paused"]) == (True, False, False)
    assert (
        out["news_share_eur"] == "1.50"
        and out["daily_run_cap"] == 10
        and out["runs_this_month"] == 1
    )


def test_the_key_test_proves_the_key_works_and_costs_almost_nothing(api, db) -> None:  # type: ignore[no-untyped-def]
    scripted = ScriptedLlm(
        message(text("ok"), model="claude-haiku-4-5-20251001", input_tokens=14, output_tokens=4)
    )
    c = api(scripted)
    assert c.post("/api/v1/agent/test").status_code == 409  # no key saved yet
    save_key(db)
    out = c.post("/api/v1/agent/test").json()
    assert (
        out["ok"] is True and out["reply"] == "ok" and out["model"] == "claude-haiku-4-5-20251001"
    )
    assert D(out["cost_eur"]) < D("0.0001")
    assert scripted.requests[0]["model"] == "claude-haiku-4-5-20251001"  # the cheapest model
    assert scripted.headers[0]["x-api-key"] == KEY
    assert KEY not in c.get("/api/v1/settings/agent").text  # the key is masked everywhere


def test_a_refused_key_is_reported_for_the_owner_to_fix(api, db) -> None:  # type: ignore[no-untyped-def]
    save_key(db)
    c = api(ScriptedLlm(error(401, "authentication_error", "invalid x-api-key")))
    out = c.post("/api/v1/agent/test")
    assert out.status_code == 422 and "refused the API key" in out.json()["detail"]
    failed = db.scalar(select(AgentRun).where(AgentRun.run_type == "test"))
    assert failed.status == "failed"


def test_a_spent_budget_stops_the_test_too(api, db) -> None:  # type: ignore[no-untyped-def]
    save_key(db, monthly_budget_eur=D("1"))
    run_with(db, "1.00", when=dt.datetime.now(dt.UTC))
    c = api(ScriptedLlm(message(text("ok"))))
    out = c.post("/api/v1/agent/test")
    assert out.status_code == 409 and "is used up" in out.json()["detail"]
    assert c.get("/api/v1/agent/usage").json()["paused"] is True


def test_the_system_page_shows_runs_cost_and_why_the_agent_is_idle(api, db) -> None:  # type: ignore[no-untyped-def]
    c = api()
    row = c.get("/api/v1/system/info").json()["agent"]
    assert (row["runs_this_month"], row["cost_this_month_eur"], row["budget_eur"]) == (
        0,
        "0.00",
        "5",
    )
    assert "Add your Anthropic API key" in row["note"]
    save_key(db)
    run_with(db, "0.50", when=dt.datetime.now(dt.UTC))
    row = c.get("/api/v1/system/info").json()["agent"]
    assert (row["runs_this_month"], row["cost_this_month_eur"], row["note"]) == (1, "0.50", None)
    save_key(db, monthly_budget_eur=D("0.5"))
    assert "budget is used up" in c.get("/api/v1/system/info").json()["agent"]["note"]
    save_key(db, enabled=False)
    assert "switched off" in c.get("/api/v1/system/info").json()["agent"]["note"]


# --- switching the agent off (FR-AG-09, NFR-06) -------------------------------------------------


def test_the_client_exists_only_when_the_agent_is_on_and_has_a_key(settings: Settings, db) -> None:  # type: ignore[no-untyped-def]
    from folio.agent.runtime import make_llm

    assert make_llm(db, settings) is None  # no key yet
    save_key(db)
    assert make_llm(db, settings) is not None
    save_key(db, enabled=False)
    assert make_llm(db, settings) is None  # switched off: the key stays saved, nothing is called
    save_key(db, key="")  # clearing the key
    assert make_llm(db, settings) is None


def test_the_job_context_builds_no_client_when_the_agent_is_off(settings: Settings, db) -> None:  # type: ignore[no-untyped-def]
    from folio.jobs.context import build_context

    ctx = build_context(settings)
    with ctx.session_factory() as session:
        assert ctx.llm_for(session) is None
        save_key(db)
        assert ctx.llm_for(session) is not None
        save_key(db, enabled=False)
        assert ctx.llm_for(session) is None
