"""The code gate between the model and the owner (FR-AG-03).

The model proposes; this module decides whether a proposal is shown. A recommendation is refused,
with the reason kept for the run trace and never shown as advice, when:

- it does not follow the output schema (appendix C), allowing enum values in any case;
- none of its evidence resolves to something this run actually saw (a signal, a news cluster, a
  tool result, a macro series, a web page the search returned);
- a trade action has no calculation from this run, or the calculation is about other subjects;
- an amount, quantity or percentage in its text is not among the numbers the tools returned
  (so a figure the model made up or changed is caught, and in privacy mode, where the tools
  return no euro amounts, any euro figure is);
- it reverses a recommendation on the same subject from the last 14 days (a trim after a
  contribution, or the other way round), unless it is critical and rests on evidence newer than
  the earlier one (anti-churn);
- it repeats another recommendation of the same run.

Pure code: the numbers and ids it checks against are handed in as `Facts`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

from folio.agent.schema import ACTION_TYPES
from folio.news.normalize import canonical_url

SEVERITIES = ("info", "low", "medium", "high", "critical")
CONFIDENCES = ("low", "medium", "high")
EVIDENCE_KINDS = ("signal", "news_cluster", "metric", "macro_series", "web_source")
TRADE_ACTIONS = ("direct_contribution", "trim", "rebalance")
BUY_SIDE, SELL_SIDE = {"direct_contribution"}, {"trim"}
ANTI_CHURN = timedelta(days=14)
MIN_EXPIRY, MAX_EXPIRY = 1, 90
DIGEST_LIMIT = 2000
LIVE_STATUSES = ("new", "seen", "accepted", "snoozed")

_REC_KEYS = {
    "action_type", "severity", "subjects", "title", "summary", "rationale", "calculation_id",
    "evidence", "sources", "confidence", "departs_from_principles", "what_would_change_this",
    "expires_in_days",
}  # fmt: skip


@dataclass(frozen=True)
class Evidence:
    kind: str
    ref: str
    note: str


@dataclass(frozen=True)
class Rec:
    action_type: str
    severity: str
    subjects: tuple[str, ...]
    title: str
    summary: str
    rationale: str
    calculation_id: str | None
    evidence: tuple[Evidence, ...]
    sources: tuple[str, ...]
    confidence: str
    departs_from_principles: str | None
    what_would_change_this: str
    expires_in_days: int


@dataclass(frozen=True)
class Calc:
    """A calculator result of this run, by what it is about and the numbers in it."""

    kind: str
    subjects: frozenset[str]
    numbers: frozenset[Decimal]


@dataclass(frozen=True)
class Past:
    """A recommendation made earlier, for the anti-churn rule."""

    subjects: frozenset[str]
    action: str
    created_at: datetime
    status: str


@dataclass
class Facts:
    """What this run actually saw: the ids and numbers a recommendation may refer to."""

    signals: Mapping[str, datetime] = field(default_factory=dict)  # signal id -> time
    clusters: Mapping[str, datetime] = field(default_factory=dict)  # news cluster id -> last seen
    tools: frozenset[str] = frozenset()  # names of the tools called
    macro: frozenset[str] = frozenset()  # macro series codes seen
    urls: frozenset[str] = frozenset()  # pages the web search returned, in canonical form
    numbers: frozenset[Decimal] = frozenset()  # every number in the tool results
    calculations: Mapping[str, Calc] = field(default_factory=dict)


@dataclass(frozen=True)
class Verdict:
    index: int
    rec: Rec | None  # the cleaned recommendation, when accepted
    reasons: tuple[str, ...]  # why it was refused, or what was corrected
    accepted: bool

    @property
    def departs(self) -> bool:
        return self.rec is not None and bool(self.rec.departs_from_principles)


@dataclass(frozen=True)
class Checked:
    digest: str
    verdicts: list[Verdict]
    problems: list[str]  # about the whole answer, not one recommendation

    @property
    def accepted(self) -> list[Rec]:
        return [v.rec for v in self.verdicts if v.accepted and v.rec is not None]


# --- reading the answer ---------------------------------------------------------------------------


def _enum(value: Any, allowed: Sequence[str]) -> str | None:
    text = str(value).strip().lower()
    return text if text in allowed else None


def _read_rec(raw: Any) -> tuple[Rec | None, list[str]]:
    if not isinstance(raw, dict):
        return None, ["not an object"]
    problems: list[str] = []
    missing = _REC_KEYS - set(raw)
    extra = set(raw) - _REC_KEYS
    if missing:
        problems.append(f"missing fields: {', '.join(sorted(missing))}")
    if extra:
        problems.append(f"unexpected fields: {', '.join(sorted(extra))}")
    if problems:
        return None, problems
    action = _enum(raw["action_type"], ACTION_TYPES)
    severity = _enum(raw["severity"], SEVERITIES)
    confidence = _enum(raw["confidence"], CONFIDENCES)
    for name, value in (
        ("action_type", action),
        ("severity", severity),
        ("confidence", confidence),
    ):
        if value is None:
            problems.append(f"{name} is not one of the allowed values")
    texts = ("title", "summary", "rationale", "what_would_change_this")
    for name in texts:
        if not isinstance(raw[name], str):
            problems.append(f"{name} is not text")
    if not isinstance(raw["subjects"], list) or not all(
        isinstance(s, str) for s in raw["subjects"]
    ):
        problems.append("subjects is not a list of text")
    if not isinstance(raw["sources"], list) or not all(isinstance(s, str) for s in raw["sources"]):
        problems.append("sources is not a list of text")
    if raw["calculation_id"] is not None and not isinstance(raw["calculation_id"], str):
        problems.append("calculation_id is neither text nor null")
    if raw["departs_from_principles"] is not None and not isinstance(
        raw["departs_from_principles"], str
    ):
        problems.append("departs_from_principles is neither text nor null")
    if isinstance(raw["expires_in_days"], bool) or not isinstance(raw["expires_in_days"], int):
        problems.append("expires_in_days is not a whole number")
    evidence: list[Evidence] = []
    if not isinstance(raw["evidence"], list):
        problems.append("evidence is not a list")
    else:
        for item in raw["evidence"]:
            kind = _enum(item.get("kind"), EVIDENCE_KINDS) if isinstance(item, dict) else None
            if (
                kind is None
                or set(item) != {"kind", "ref", "note"}
                or not isinstance(item["ref"], str)
                or not isinstance(item["note"], str)
            ):
                problems.append("an evidence item is malformed")
                break
            evidence.append(Evidence(kind, item["ref"].strip(), item["note"]))
    if problems or action is None or severity is None or confidence is None:
        return None, problems
    departs = raw["departs_from_principles"]
    return (
        Rec(
            action,
            severity,
            tuple(s.strip() for s in raw["subjects"] if s.strip()),
            raw["title"].strip(),
            raw["summary"].strip(),
            raw["rationale"].strip(),
            (raw["calculation_id"] or "").strip() or None,
            tuple(evidence),
            tuple(raw["sources"]),
            confidence,
            departs.strip() if isinstance(departs, str) and departs.strip() else None,
            raw["what_would_change_this"].strip(),
            max(MIN_EXPIRY, min(MAX_EXPIRY, raw["expires_in_days"])),
        ),
        [],
    )


# --- numbers in text ------------------------------------------------------------------------------

_AMOUNT = re.compile(
    r"(?P<pre>[€$]\s?|EUR\s|USD\s)?"
    r"(?P<num>\d{1,3}(?:[.,  ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"(?P<post>\s?(?:%|pp\b|percent\b|percentage points?\b|units?\b|shares?\b"
    r"|EUR\b|euros?\b|USD\b))?",
    re.IGNORECASE,
)


def _candidates(token: str) -> set[Decimal]:
    """The values a written number can mean: "1.234" is 1.234 or 1234, "1,5" is 1.5."""
    cleaned = token.replace(" ", "").replace(" ", "")
    out: set[Decimal] = set()
    forms = [cleaned.replace(",", ""), cleaned.replace(".", "").replace(",", ".")]
    if "," in cleaned and "." not in cleaned:
        forms.append(cleaned.replace(",", "."))
    for form in forms:
        try:
            out.add(Decimal(form))
        except InvalidOperation:
            continue
    return out


def _decimals(token: str) -> int:
    tail = re.split(r"[.,]", token)[-1]
    return len(tail) if re.search(r"[.,]\d{1,2}$", token) else 0


def unsupported_numbers(text: str, facts: frozenset[Decimal]) -> list[str]:
    """Amounts, quantities and percentages written in `text` that no tool returned. A bare
    number (a date, "14 days") is not checked; one with a currency sign, a percent sign, "pp"
    or "units" is."""
    bad: list[str] = []
    for m in _AMOUNT.finditer(text):
        pre, post = m.group("pre"), m.group("post")
        if not pre and not post:
            continue
        token = m.group("num")
        kind = (post or "").strip().lower()
        percent = kind in ("%", "pp", "percent") or kind.startswith("percentage")
        slack = Decimal(5) * Decimal(10) ** -(_decimals(token) + 1)
        scale = (Decimal(1), Decimal(100)) if percent else (Decimal(1),)
        found = any(
            abs(value - fact * s) <= slack
            for value in _candidates(token)
            for fact in facts
            for s in scale
        )
        if not found:
            bad.append(m.group(0).strip())
    return bad


# --- the checks -----------------------------------------------------------------------------------


def _resolve(e: Evidence, facts: Facts) -> datetime | bool:
    """The time of the thing the evidence refers to, True when it exists but has no time, or
    False when it does not resolve."""
    if e.kind == "signal":
        return facts.signals.get(e.ref, False)
    if e.kind == "news_cluster":
        return facts.clusters.get(e.ref, False)
    if e.kind == "metric":
        return e.ref in facts.tools or e.ref.split(":", 1)[0] in facts.tools
    if e.kind == "macro_series":
        return e.ref in facts.macro
    return canonical_url(e.ref) in facts.urls


def _is_https(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and bool(parts.netloc)


def _opposite(a: str, b: str) -> bool:
    return (a in BUY_SIDE and b in SELL_SIDE) or (a in SELL_SIDE and b in BUY_SIDE)


def check_one(index: int, rec: Rec, facts: Facts, past: Sequence[Past], now: datetime) -> Verdict:
    reasons: list[str] = []
    kept: list[Evidence] = []
    times: list[datetime] = []
    for e in rec.evidence:
        resolved = _resolve(e, facts)
        if resolved is False:
            reasons.append(f"evidence {e.kind} {e.ref!r} was not seen in this run")
            continue
        kept.append(e)
        if isinstance(resolved, datetime):
            times.append(resolved)
    if not kept:
        return Verdict(index, None, ("no evidence that this run actually saw", *reasons), False)

    refusals: list[str] = []
    if rec.action_type in TRADE_ACTIONS:
        calc = facts.calculations.get(rec.calculation_id or "")
        if calc is None:
            refusals.append("a trade needs a calculation from this run")
        elif rec.subjects and calc.subjects and not set(rec.subjects) & calc.subjects:
            refusals.append("the calculation is about other subjects")
    elif rec.calculation_id is not None and rec.calculation_id not in facts.calculations:
        refusals.append("the calculation it cites does not exist")

    text = " ".join((rec.title, rec.summary, rec.rationale, rec.what_would_change_this))
    allowed = set(facts.numbers)
    calc = facts.calculations.get(rec.calculation_id or "")
    if calc is not None:
        allowed |= calc.numbers
    for token in unsupported_numbers(text, frozenset(allowed)):
        refusals.append(f"the figure {token!r} is not in any tool result or calculation")

    for p in past:
        if (
            p.status in LIVE_STATUSES
            and now - p.created_at <= ANTI_CHURN
            and p.subjects & set(rec.subjects)
            and _opposite(rec.action_type, p.action)
        ):
            newer = any(t > p.created_at for t in times)
            if not (rec.severity == "critical" and newer):
                refusals.append(
                    f"it reverses a {p.action} recommendation from the last 14 days without "
                    "critical severity and newer evidence"
                )

    if refusals:
        return Verdict(index, None, (*refusals, *reasons), False)
    cleaned = Rec(
        rec.action_type,
        rec.severity,
        rec.subjects,
        rec.title,
        rec.summary,
        rec.rationale,
        rec.calculation_id,
        tuple(kept),
        tuple(s for s in rec.sources if _is_https(s)),
        rec.confidence,
        rec.departs_from_principles,
        rec.what_would_change_this,
        rec.expires_in_days,
    )
    dropped = len(rec.sources) - len(cleaned.sources)
    if dropped:
        reasons.append(f"{dropped} source(s) without an https address were dropped")
    return Verdict(index, cleaned, tuple(reasons), True)


def check_output(
    data: Any, facts: Facts, past: Sequence[Past] = (), now: datetime | None = None
) -> Checked:
    """Check a composed answer (already parsed from JSON): the digest and each recommendation."""
    when = now or datetime.now().astimezone()
    if not isinstance(data, dict) or set(data) != {"digest", "recommendations"}:
        return Checked("", [], ["The answer does not follow the output schema."])
    digest = data["digest"] if isinstance(data["digest"], str) else ""
    if not isinstance(data["recommendations"], list):
        return Checked(digest[:DIGEST_LIMIT], [], ["recommendations is not a list."])
    verdicts: list[Verdict] = []
    seen: set[tuple[str, frozenset[str]]] = set()
    for index, raw in enumerate(data["recommendations"]):
        rec, problems = _read_rec(raw)
        if rec is None:
            verdicts.append(Verdict(index, None, tuple(f"schema: {p}" for p in problems), False))
            continue
        verdict = check_one(index, rec, facts, past, when)
        key = (rec.action_type, frozenset(rec.subjects))
        if verdict.accepted and key in seen:
            verdict = Verdict(
                index, None, ("it repeats another recommendation of this run",), False
            )
        elif verdict.accepted:
            seen.add(key)
        verdicts.append(verdict)
    return Checked(digest.strip()[:DIGEST_LIMIT], verdicts, [])
