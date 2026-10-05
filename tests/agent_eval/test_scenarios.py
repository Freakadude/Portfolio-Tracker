"""The evaluation scenarios against the code gate (FR-AG-02, FR-AG-03)."""

import pytest

from folio.agent.validate import check_output
from tests.agent_eval.harness import SCENARIOS, Scenario, all_scenarios

SET = all_scenarios()


@pytest.mark.parametrize("scenario", SET, ids=[s.name for s in SET])
def test_the_gate_does_what_the_scenario_expects(scenario: Scenario) -> None:
    checked = check_output(scenario.output, scenario.facts, scenario.past, scenario.now)
    expect = scenario.expect
    assert checked.problems == []
    assert [v.index for v in checked.verdicts if v.accepted] == expect["accepted"]
    refused = {str(v.index): v for v in checked.verdicts if not v.accepted}
    assert set(refused) == set(expect["rejected"])
    for index, fragment in expect["rejected"].items():
        assert any(fragment in r for r in refused[index].reasons), (index, refused[index].reasons)
        assert refused[index].rec is None  # a refused item is never kept as advice
    if "digest_contains" in expect:
        assert expect["digest_contains"] in checked.digest
    if "departs" in expect:
        assert [v.index for v in checked.verdicts if v.departs] == expect["departs"]
    for index, fragment in expect.get("notes", {}).items():
        note = checked.verdicts[int(index)].reasons
        assert any(fragment in r for r in note), (index, note)
    for index, urls in expect.get("sources", {}).items():
        rec = checked.verdicts[int(index)].rec
        assert rec is not None and list(rec.sources) == urls
    for index, days in expect.get("expires", {}).items():
        rec = checked.verdicts[int(index)].rec
        assert rec is not None and rec.expires_in_days == days


def test_every_scenario_accounts_for_every_recommendation() -> None:
    for s in SET:
        count = len(s.output["recommendations"])
        decided = set(map(str, s.expect["accepted"])) | set(s.expect["rejected"])
        assert decided == {str(i) for i in range(count)}, s.name


def test_the_set_covers_what_the_spec_asks_for() -> None:
    names = {s.name for s in SET}
    for needed in (
        "01_drift_with_calculation",  # a recommendation that passes
        "02_nothing_to_report",  # FR-AG-01: nothing to report, nothing made
        "03_altered_amount",  # FR-AG-03 acceptance
        "04_churn",  # anti-churn
        "05_principle_departure",  # FR-ST-07
        "07_injection_followed",  # untrusted content
    ):
        assert needed in names
    assert len(list(SCENARIOS.glob("*.json"))) == len(SET) >= 10
