# ruff: noqa: F811  (the fixtures are imported from other test modules and used as parameters)
"""The projection endpoint (FR-PF-12): the portfolio's value as the start, the owner's assumptions
echoed, a month per point, and what the portfolio did in the last year to guide the choice."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from tests.conftest import PASSWORD, USERNAME
from tests.integration.test_agent_run import world  # noqa: F401
from tests.integration.test_news_pipeline import NOW, book, db  # noqa: F401

D = Decimal
URL = "/api/v1/portfolio/projection"
ASOF = NOW.date().isoformat()  # 2024-03-15: the book is worth 2 500 (flat prices)


@pytest.fixture
def api(make_client: Callable[..., TestClient], owner: None) -> TestClient:
    c = make_client()
    c.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return c


def test_it_starts_from_the_value_of_the_portfolio_and_echoes_the_assumptions(
    api: TestClient, world
) -> None:
    body = api.get(
        URL,
        params={
            "as_of": ASOF, "years": 2, "monthly_contribution": 100, "return_pct": 0,
            "volatility_pct": 0, "paths": 200, "seed": 7,
        },
    ).json()  # fmt: skip
    a = body["assumptions"]
    assert D(a["start_value_eur"]) == D(2500)
    assert (D(a["monthly_contribution_eur"]), a["years"], a["paths"], a["seed"]) == (
        D(100),
        2,
        200,
        7,
    )
    assert (D(a["annual_return_pct"]), D(a["annual_volatility_pct"])) == (0, 0)
    points = body["points"]
    assert len(points) == 25 and points[0]["month"] == 0 and points[-1]["month"] == 24
    assert D(points[0]["median_eur"]) == D(2500)
    # no return, no volatility: the median is exactly what was paid in
    assert D(points[24]["invested_eur"]) == D(4900) and D(points[24]["median_eur"]) == D(4900)
    assert D(points[24]["p10_eur"]) == D(points[24]["p90_eur"]) == D(4900)
    assert points[1]["date"] == "2024-04-15" and points[12]["date"] == "2025-03-15"
    assert "not a forecast" in body["note"] and "200 paths" in body["note"]


def test_a_month_end_start_clamps_the_dates(api: TestClient, world) -> None:
    points = api.get(URL, params={"as_of": "2024-01-31", "years": 1}).json()["points"]
    assert [points[i]["date"] for i in (1, 2, 3)] == ["2024-02-29", "2024-03-31", "2024-04-30"]


def test_a_band_opens_up_with_volatility_and_the_default_assumptions_are_stated(
    api: TestClient, world
) -> None:
    body = api.get(URL, params={"as_of": ASOF, "years": 10}).json()
    a = body["assumptions"]
    assert (D(a["annual_return_pct"]), D(a["annual_volatility_pct"]), a["years"]) == (5, 15, 10)
    assert D(a["monthly_contribution_eur"]) == 0  # no contribution plan (Q4)
    last = body["points"][-1]
    assert D(last["p10_eur"]) < D(last["median_eur"]) < D(last["p90_eur"])
    assert D(last["median_eur"]) > D(last["invested_eur"])  # 5 % a year on 2 500 for 10 years


def test_the_same_seed_repeats_and_another_changes_the_chart(api: TestClient, world) -> None:
    params = {"as_of": ASOF, "years": 3, "paths": 300}
    first = api.get(URL, params={**params, "seed": 1}).json()["points"]
    assert api.get(URL, params={**params, "seed": 1}).json()["points"] == first
    assert api.get(URL, params={**params, "seed": 2}).json()["points"] != first


def test_what_the_portfolio_did_in_the_last_year_is_offered_to_guide_the_choice(
    api: TestClient, world
) -> None:
    measured = api.get(URL, params={"as_of": ASOF}).json()["measured"]
    assert measured["end"] == ASOF and measured["start"] >= "2024-01-01"
    assert D(measured["annual_volatility_pct"]) == 0 and D(measured["annual_return_pct"]) == 0


def test_without_any_transactions_it_still_shows_what_saving_would_build(
    api: TestClient,
) -> None:
    body = api.get(
        URL, params={"years": 1, "monthly_contribution": 200, "return_pct": 0, "volatility_pct": 0}
    ).json()
    assert D(body["assumptions"]["start_value_eur"]) == 0 and body["measured"] is None
    assert D(body["points"][-1]["median_eur"]) == D(2400)
    assert body["as_of"] == date.today().isoformat()


@pytest.mark.parametrize(
    "params",
    [
        {"years": 0}, {"years": 41}, {"paths": 99}, {"paths": 5001}, {"volatility_pct": 101},
        {"return_pct": -51}, {"monthly_contribution": -1}, {"seed": -1},
    ],
)  # fmt: skip
def test_assumptions_outside_their_limits_are_refused(
    api: TestClient, params: dict[str, int]
) -> None:
    assert api.get(URL, params=params).status_code == 422


def test_the_projection_needs_a_login(client: TestClient, owner: None) -> None:
    assert client.get(URL).status_code == 401
