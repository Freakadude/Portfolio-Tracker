"""The agent evaluation set (NFR-12): fixed scenarios, each a state of the world, a recorded model
output and what the code gate must do with it. They run in CI and are the reference for tuning
prompts: change a prompt, and these (and the recorded runs that replay them) must still pass.

A scenario file is JSON:

    description  what the scenario is about
    now          the moment of the run
    facts        what the run saw: signals {id: time}, clusters {id: time}, tools, macro, urls,
                 numbers, calculations {id: {kind, subjects, numbers}}
    past         recommendations made earlier {subjects, action, created_at, status}
    output       the composed answer as the model gave it (spec appendix C)
    expect       accepted [indexes], rejected {index: reason substring}, optional departs [indexes],
                 digest_contains, notes {index: substring}, sources {index: [urls]},
                 expires {index: days}
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from folio.agent.validate import Calc, Facts, Past

SCENARIOS = Path(__file__).resolve().parent / "scenarios"


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    now: datetime
    facts: Facts
    past: list[Past]
    output: Any
    expect: dict[str, Any]


def _time(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _decimals(values: list[str]) -> frozenset[Decimal]:
    return frozenset(Decimal(v) for v in values)


def load(path: Path) -> Scenario:
    raw = json.loads(path.read_text(encoding="utf-8"))
    f = raw.get("facts", {})
    facts = Facts(
        signals={k: _time(v) for k, v in f.get("signals", {}).items()},
        clusters={k: _time(v) for k, v in f.get("clusters", {}).items()},
        tools=frozenset(f.get("tools", [])),
        macro=frozenset(f.get("macro", [])),
        urls=frozenset(f.get("urls", [])),
        numbers=_decimals(f.get("numbers", [])),
        calculations={
            cid: Calc(c["kind"], frozenset(c["subjects"]), _decimals(c["numbers"]))
            for cid, c in f.get("calculations", {}).items()
        },
    )
    past = [
        Past(frozenset(p["subjects"]), p["action"], _time(p["created_at"]), p["status"])
        for p in raw.get("past", [])
    ]
    return Scenario(
        path.stem, raw["description"], _time(raw["now"]), facts, past, raw["output"], raw["expect"]
    )


def all_scenarios() -> list[Scenario]:
    return [load(p) for p in sorted(SCENARIOS.glob("*.json"))]
