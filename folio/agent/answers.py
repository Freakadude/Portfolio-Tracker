"""The code gate for the answer to a question about the portfolio (FR-AG-08, FR-DB-09).

Pure, like the gate for recommendations (`validate.py`, FR-AG-03): an answer is shown only if it
cites tools this run really called and every amount, quantity, weight or percentage written in it
is a number a tool returned. An answer that fails is not shown as an answer; the reasons are kept
in the run's trace. The same helpers that check recommendations do the number check.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from folio.agent.validate import Facts, unsupported_numbers

ANSWER_LIMIT = 3000
NOTE_LIMIT = 300


@dataclass(frozen=True)
class Citation:
    tool: str
    note: str


@dataclass(frozen=True)
class Answer:
    text: str
    citations: tuple[Citation, ...]
    not_found: str


@dataclass(frozen=True)
class Verdict:
    answer: Answer | None  # the cleaned answer, when it passed
    reasons: tuple[str, ...] = field(default=())

    @property
    def accepted(self) -> bool:
        return self.answer is not None


def _text(value: Any, limit: int) -> str | None:
    return " ".join(value.split())[:limit] if isinstance(value, str) else None


def check_answer(data: Any, facts: Facts) -> Verdict:
    """Read and check the structured answer against what the run saw."""
    if not isinstance(data, dict):
        return Verdict(None, ("the answer is not in the agreed structure",))
    reasons: list[str] = []
    body = data.get("answer")
    answer = body.strip()[:ANSWER_LIMIT] if isinstance(body, str) else ""
    if not answer:
        reasons.append("the answer is empty")
    not_found = _text(data.get("not_found"), NOTE_LIMIT)
    if not_found is None:
        reasons.append("not_found is missing")
        not_found = ""
    raw = data.get("citations")
    citations: list[Citation] = []
    if not isinstance(raw, list):
        reasons.append("the citations are missing")
    else:
        for item in raw:
            tool = _text(item.get("tool"), 80) if isinstance(item, dict) else None
            note = _text(item.get("note"), NOTE_LIMIT) if isinstance(item, dict) else None
            if not tool or note is None:
                reasons.append("a citation does not name a tool and a note")
                continue
            if tool not in facts.tools and not (tool == "web_search" and facts.urls):
                reasons.append(f"it cites {tool}, which this run did not use")
                continue
            citations.append(Citation(tool, note))
    if not citations and not any("cites" in r or "citation" in r for r in reasons):
        reasons.append("it cites none of the data it used")
    unsupported = unsupported_numbers(f"{answer} {not_found}", facts.numbers)
    if unsupported:
        reasons.append(
            "a figure in the answer was not in the data this run read: "
            + ", ".join(unsupported[:5])
        )
    if reasons:
        return Verdict(None, tuple(reasons))
    return Verdict(Answer(answer, tuple(citations), not_found))


def data_used(
    citations: Sequence[Citation], tool_calls: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """For each cited tool, the first call this run made to it, with its input and what it
    returned, so the owner can read the rows the answer rests on."""
    out: list[dict[str, Any]] = []
    for citation in citations:
        call = next((c for c in tool_calls if c.get("name") == citation.tool), None)
        out.append(
            {
                "tool": citation.tool,
                "note": citation.note,
                "input": {} if call is None else call.get("input") or {},
                "result": "" if call is None else str(call.get("result") or ""),
            }
        )
    return out
