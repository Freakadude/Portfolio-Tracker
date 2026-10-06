"""The code gate for answers to questions about the portfolio (FR-AG-08): the citations must name
tools the run used, and every figure must be one a tool returned."""

from decimal import Decimal

from folio.agent.answers import Citation, check_answer, data_used
from folio.agent.validate import Facts

D = Decimal
FACTS = Facts(
    tools=frozenset({"get_signals", "get_portfolio_summary"}),
    numbers=frozenset({D("20.0"), D("0.4"), D("10"), D("1234.56")}),
    urls=frozenset(),
)


def answer(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "answer": "Gold is 20.0 pp under its target.",
        "citations": [{"tool": "get_signals", "note": "the drift signal"}],
        "not_found": "",
    }
    base.update(over)
    return base


def test_a_cited_answer_whose_figures_were_read_passes() -> None:
    verdict = check_answer(answer(), FACTS)
    assert verdict.accepted and verdict.reasons == ()
    assert verdict.answer is not None
    assert verdict.answer.text == "Gold is 20.0 pp under its target."
    assert verdict.answer.citations == (Citation("get_signals", "the drift signal"),)


def test_a_figure_no_tool_returned_is_refused() -> None:
    verdict = check_answer(answer(answer="Gold is 35.5 pp under its target."), FACTS)
    assert not verdict.accepted and verdict.answer is None
    assert verdict.reasons == ("a figure in the answer was not in the data this run read: 35.5 pp",)


def test_euro_amounts_need_a_tool_result_too_so_privacy_mode_keeps_them_out() -> None:
    assert not check_answer(answer(answer="You hold EUR 999.99 of gold."), FACTS).accepted
    assert not check_answer(answer(answer="You hold € 999.99 of gold."), FACTS).accepted
    assert check_answer(answer(answer="Your largest holding is € 1,234.56."), FACTS).accepted


def test_a_percentage_may_be_written_from_a_weight() -> None:
    assert check_answer(answer(answer="Gold weighs 40% of the portfolio."), FACTS).accepted


def test_a_citation_must_name_a_tool_the_run_used() -> None:
    verdict = check_answer(
        answer(citations=[{"tool": "run_calculator", "note": "an order"}]), FACTS
    )
    assert verdict.reasons == ("it cites run_calculator, which this run did not use",)


def test_an_answer_with_no_citations_is_refused() -> None:
    assert check_answer(answer(citations=[]), FACTS).reasons == (
        "it cites none of the data it used",
    )
    assert "the citations are missing" in check_answer(answer(citations=None), FACTS).reasons


def test_web_search_can_be_cited_only_after_it_returned_pages() -> None:
    cited = answer(citations=[{"tool": "web_search", "note": "the issuer's page"}])
    assert not check_answer(cited, FACTS).accepted
    with_pages = Facts(
        tools=FACTS.tools, numbers=FACTS.numbers, urls=frozenset({"https://a.example"})
    )
    assert check_answer(cited, with_pages).accepted


def test_a_malformed_answer_is_refused_with_its_reasons() -> None:
    assert check_answer("nope", FACTS).reasons == ("the answer is not in the agreed structure",)
    verdict = check_answer({"answer": "  ", "citations": [{"tool": 1}], "not_found": None}, FACTS)
    assert not verdict.accepted
    assert {
        "the answer is empty",
        "not_found is missing",
        "a citation does not name a tool and a note",
    } <= set(verdict.reasons)


def test_what_could_not_be_found_is_checked_like_the_answer() -> None:
    ok = check_answer(answer(not_found="No price for the benchmark."), FACTS)
    assert ok.accepted and ok.answer is not None
    assert ok.answer.not_found == "No price for the benchmark."
    assert not check_answer(answer(not_found="Missing 77 units."), FACTS).accepted


def test_the_data_used_lists_the_first_call_of_each_cited_tool() -> None:
    calls = [
        {"name": "get_portfolio_summary", "input": {"as_of": None}, "result": "weights ..."},
        {"name": "get_signals", "input": {"state": "open"}, "result": "gold 20.0 pp"},
        {"name": "get_signals", "input": {"state": "all"}, "result": "later"},
    ]
    rows = data_used([Citation("get_signals", "drift")], calls)
    assert rows == [
        {
            "tool": "get_signals",
            "note": "drift",
            "input": {"state": "open"},
            "result": "gold 20.0 pp",
        }
    ]
