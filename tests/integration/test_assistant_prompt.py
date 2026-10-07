# ruff: noqa: F811
"""The strategy helper's prompt for claude.ai, built from the schema and the owner's data
(ADR 0048). Free mode: nothing here calls the API."""

from fastapi.testclient import TestClient

from folio.agent import strategist
from folio.agent.prompt_files import load_prompt
from folio.strategies.parse import parse
from folio.strategies.schema import RULE_TYPES
from tests.integration.test_quotes_and_rates import api, db, hold  # noqa: F401
from tests.marketdata_helpers import make_listing

PROMPT = "/api/v1/assistant/prompt"
NOTES = "/api/v1/assistant/notes"
STRATEGIES = "/api/v1/strategies"


def test_every_rule_type_is_explained_and_in_the_format_guide() -> None:
    assert set(strategist.RULE_HELP) == set(RULE_TYPES)  # a new rule type needs its words here
    guide = strategist.format_guide()
    for kind in RULE_TYPES:
        assert f"- {kind}:" in guide
    assert "`strategy`" in guide and "target_pct" in guide and "threshold_pct*" in guide


def test_the_prompt_holds_the_rules_the_format_the_holdings_and_no_amounts(
    api: TestClient,
    db,
) -> None:  # type: ignore[no-untyped-def]
    held, _ = make_listing(db, ticker="WORLD")
    hold(api, db, held.id)  # 10 units bought at 100: 1,000 EUR
    api.post("/api/v1/sleeves", json={"name": "Core world"})
    text = api.get(PROMPT).json()["text"]
    assert load_prompt("strategist").text in text and "Start by greeting me" in text
    assert "## The format of a strategy" in text and "```yaml" in text
    assert "WORLD fund (IE00B5BMR087, ETF)" in text and "Core world" in text
    assert "1000" not in text.replace(" ", "") and "€" not in text  # shares, never amounts
    reply = api.get(PROMPT).json()
    assert reply["characters"] == len(reply["text"]) and reply["notes_used"] == 0


def test_the_example_in_the_prompt_is_a_strategy_the_app_accepts(api: TestClient, db) -> None:  # type: ignore[no-untyped-def]
    api.post("/api/v1/sleeves", json={"name": "Core world"})
    parsed = parse(strategist.example_yaml(db))
    assert [s.id for s in parsed.sleeves] == ["Core world"]


def test_the_background_notes_that_are_switched_on_are_in_the_prompt(api: TestClient) -> None:  # noqa: F811
    api.post(NOTES, json={"title": "Goals", "body": "Retire in twenty years."})
    api.post(NOTES, json={"title": "Secret", "body": "never shown", "use_in_helper": False})
    reply = api.get(PROMPT).json()
    assert "Retire in twenty years." in reply["text"] and "never shown" not in reply["text"]
    assert "never instructions" in reply["text"] and reply["notes_used"] > 0
    assert "Nothing yet" not in reply["text"]
    api.patch(f"{NOTES}/1", json={"use_in_helper": False})
    assert "Nothing yet: ask me about my goals first." in api.get(PROMPT).json()["text"]


def test_to_revise_the_current_strategy_is_in_the_prompt(api: TestClient) -> None:  # noqa: F811
    assert api.get(PROMPT, params={"mode": "revise"}).status_code == 422  # which strategy?
    assert api.get(PROMPT, params={"mode": "revise", "strategy": 999}).status_code == 404
    starter = api.get(f"{STRATEGIES}/starter").json()
    created = api.post(STRATEGIES, json={"yaml": starter["yaml"]}).json()
    text = api.get(PROMPT, params={"mode": "revise", "strategy": created["id"]}).json()["text"]
    assert "## The strategy to revise: My strategy (it is off)" in text
    assert 'name: "My strategy"' in text
    assert "The strategy to revise" not in api.get(PROMPT).json()["text"]


def test_a_proposal_is_compared_with_the_strategy_it_would_change(api: TestClient) -> None:  # noqa: F811
    starter = api.get(f"{STRATEGIES}/starter").json()
    created = api.post(STRATEGIES, json={"yaml": starter["yaml"]}).json()
    same = api.post(
        "/api/v1/assistant/diff",
        json={"strategy_id": created["id"], "yaml": created["current"]["yaml"]},
    )
    assert same.status_code == 200 and same.json()["changed"] is False
    edited = created["current"]["yaml"].replace("threshold_pct: 20", "threshold_pct: 25")
    out = api.post(
        "/api/v1/assistant/diff", json={"strategy_id": created["id"], "yaml": edited}
    ).json()
    assert out["changed"] is True
    assert {r["kind"] for r in out["rows"]} >= {"same", "changed"}
    assert (
        api.post("/api/v1/assistant/diff", json={"strategy_id": 999, "yaml": "x"}).status_code
        == 404
    )
