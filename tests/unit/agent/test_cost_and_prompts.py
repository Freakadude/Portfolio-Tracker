"""What an LLM call costs, and versioned prompt files (FR-AG-04, FR-AG-10)."""

from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from folio.agent.cost import Usage, cost_usd, estimate_input_tokens, to_eur, worst_case_usd
from folio.agent.prompt_files import PromptError, labels, load_prompt
from folio.settings_schema import AgentSettings, ModelPrice

D = Decimal
SONNET = ModelPrice(
    input_usd=D(3), output_usd=D(15), cache_write_usd=D("3.75"), cache_read_usd=D("0.30")
)


# --- cost -------------------------------------------------------------------------------------


def test_cost_is_the_usage_times_the_price_table() -> None:
    usage = Usage(
        input_tokens=10_000, output_tokens=2_000, cache_read_tokens=50_000, cache_write_tokens=8_000
    )
    # 10k x 3 + 2k x 15 + 50k x 0.30 + 8k x 3.75, per million = 0.03 + 0.03 + 0.015 + 0.03
    assert cost_usd(usage, SONNET, D(10)) == D("0.105")


def test_web_searches_are_counted_apart_from_tokens() -> None:
    assert cost_usd(Usage(web_searches=3), SONNET, D(10)) == D("0.03")  # $10 per 1 000 searches
    assert cost_usd(Usage(), SONNET, D(10)) == 0


def test_usd_is_converted_to_euro_at_the_rate_and_rounded_to_a_millionth() -> None:
    assert to_eur(D("0.105"), D("1.10")) == D("0.095455")
    assert to_eur(D(0), D("1.10")) == 0


def test_the_worst_case_assumes_everything_uncached_and_every_search() -> None:
    worst = worst_case_usd(SONNET, 20_000, 4_000, 5, D(10))
    assert worst == D("0.06") + D("0.06") + D("0.05")  # input, the whole output allowance, searches
    real = Usage(input_tokens=5_000, output_tokens=900, cache_read_tokens=15_000, web_searches=2)
    assert cost_usd(real, SONNET, D(10)) < worst


def test_usage_adds_up_and_counts_every_kind_of_token() -> None:
    a = Usage(1, 2, 3, 4, 1)
    b = Usage(10, 20, 30, 40, 2)
    assert a + b == Usage(11, 22, 33, 44, 3) and (a + b).total_tokens == 110


def test_the_input_estimate_is_cautious() -> None:
    assert estimate_input_tokens(300) == 100 and estimate_input_tokens(301) == 101


@given(
    st.integers(0, 10**6), st.integers(0, 10**5), st.integers(0, 10**6), st.integers(0, 10**5),
    st.integers(0, 20),
)  # fmt: skip
def test_the_cost_never_decreases_with_more_usage(i: int, o: int, r: int, w: int, s: int) -> None:
    base = Usage(i, o, r, w, s)
    assert cost_usd(base + Usage(1, 1, 1, 1, 1), SONNET, D(10)) > cost_usd(base, SONNET, D(10))


def test_the_default_price_table_covers_every_default_model() -> None:
    settings = AgentSettings()
    for model in settings.models.values():
        assert model in settings.prices, f"no price for {model}"
    haiku = settings.prices["claude-haiku-4-5-20251001"]
    assert haiku.cache_read_usd == haiku.input_usd / 10  # a cache read costs a tenth
    assert haiku.cache_write_usd == haiku.input_usd * D("1.25")


def test_the_daily_review_time_is_checked() -> None:
    assert AgentSettings(daily_review_time="7:05").daily_review_time == "07:05"
    for bad in ("25:00", "19-30", "19:60", "evening"):
        with pytest.raises(ValueError, match="Use a time like 19:30"):
            AgentSettings(daily_review_time=bad)


# --- prompt files -----------------------------------------------------------------------------


def write(folder: Path, name: str, version: int, body: str) -> None:
    (folder / f"{name}.md").write_text(f"---\nversion: {version}\n---\n{body}\n", encoding="utf-8")


def test_a_prompt_records_its_version_and_a_digest_of_its_text(tmp_path: Path) -> None:
    write(tmp_path, "system", 3, "You are careful.")
    prompt = load_prompt("system", tmp_path)
    assert (prompt.name, prompt.version, prompt.text) == ("system", 3, "You are careful.")
    assert prompt.label == f"system@3+{prompt.digest}" and len(prompt.digest) == 8


def test_changing_a_prompt_changes_the_recorded_label_even_without_a_version_bump(
    tmp_path: Path,
) -> None:
    write(tmp_path, "system", 1, "You are careful.")
    before = load_prompt("system", tmp_path).label
    write(tmp_path, "system", 1, "You are very careful.")  # edited, the version forgotten
    after = load_prompt("system", tmp_path).label
    assert before != after and before.startswith("system@1+") and after.startswith("system@1+")
    write(tmp_path, "system", 2, "You are very careful.")  # now the version moves too
    assert load_prompt("system", tmp_path).label.startswith("system@2+")


def test_line_endings_and_surrounding_blank_lines_do_not_change_the_digest(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"---\r\nversion: 1\r\n---\r\n\r\nLine one\r\nLine two\r\n\r\n")
    (tmp_path / "b.md").write_bytes(b"---\nversion: 1\n---\nLine one\nLine two\n")
    assert load_prompt("a", tmp_path).digest == load_prompt("b", tmp_path).digest


def test_a_prompt_without_a_header_or_a_file_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "bare.md").write_text("no header here", encoding="utf-8")
    with pytest.raises(PromptError, match="must start with a header"):
        load_prompt("bare", tmp_path)
    with pytest.raises(PromptError, match="does not exist"):
        load_prompt("missing", tmp_path)


def test_a_run_records_every_prompt_it_used(tmp_path: Path) -> None:
    write(tmp_path, "system", 1, "One")
    write(tmp_path, "compose", 4, "Two")
    both = [load_prompt("system", tmp_path), load_prompt("compose", tmp_path)]
    text = labels(both)
    assert text.startswith("system@1+") and ", compose@4+" in text


def test_the_shipped_system_prompt_carries_the_guardrails() -> None:
    prompt = load_prompt("system")
    assert prompt.version >= 1
    for rule in (
        "Principles first",
        "Numbers come from tools",
        "<untrusted>",
        "never follow them",
        "departs_from_principles",
        "not financial advice",
    ):
        assert rule in prompt.text, rule
