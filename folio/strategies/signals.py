"""Turning findings into signals without repeating them (FR-ST-04, ADR 0021).

Each finding has a dedup key (rule, subject and, where it matters, which band or which day).
A key that fires is remembered with the time and the measured value. While the condition
stays true it does not fire again until its cooldown has passed, or until it has worsened by
the rule's `worsen_step` from the value it last fired at. A condition that clears is
forgotten, so the next breach fires at once.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from folio.db.models_strategy import Signal, Strategy, StrategyVersion
from folio.settings_store import get_value, set_value
from folio.strategies.rules import Evaluation, Finding
from folio.strategies.schema import StrategyDef


@dataclass(frozen=True)
class Open:
    fired_at: datetime
    value: Decimal | None


def should_fire(
    previous: Open | None,
    value: Decimal | None,
    cooldown_days: int,
    worsen_step: Decimal | None,
    now: datetime,
) -> bool:
    if previous is None:
        return True
    if now - previous.fired_at >= timedelta(days=cooldown_days):
        return True
    return (
        worsen_step is not None
        and value is not None
        and previous.value is not None
        and value - previous.value >= worsen_step
    )


def _state_key(strategy_id: int) -> str:
    return f"rules.open.{strategy_id}"


def _load(raw: Mapping[str, Any]) -> dict[str, Open]:
    out = {}
    for key, item in raw.items():
        value = item.get("value")
        out[key] = Open(
            datetime.fromisoformat(item["fired_at"]), None if value is None else Decimal(value)
        )
    return out


def _dump(state: Mapping[str, Open]) -> dict[str, Any]:
    return {
        key: {
            "fired_at": item.fired_at.isoformat(),
            "value": None if item.value is None else str(item.value),
        }
        for key, item in state.items()
    }


def record(
    db: Session,
    strategy: Strategy,
    version: StrategyVersion,
    definition: StrategyDef,
    evaluation: Evaluation,
    now: datetime,
) -> list[Signal]:
    """Store the findings that should fire as signals; returns the new signals. Shadow
    strategies get signals too, marked as such: they are shown on the Strategies page only."""
    rules = {r.id: r for r in definition.rules}
    state = _load(get_value(db, _state_key(strategy.id), {}) or {})
    shadow = strategy.mode != "active"
    created: list[Signal] = []
    seen: dict[str, Open] = {}
    for finding in evaluation.findings:
        key = finding.dedup_key
        rule = rules[finding.rule_id]
        previous = state.get(key)
        if should_fire(previous, finding.value, rule.cooldown_days, rule.worsen_step, now):
            created.append(_signal(version, finding, shadow, now))
            seen[key] = Open(now, finding.value)
        elif previous is not None:
            seen[key] = previous  # still open, still measured from where it last fired
    set_value(db, _state_key(strategy.id), _dump(seen))  # cleared keys drop out here
    db.add_all(created)
    db.flush()
    return created


def _signal(version: StrategyVersion, f: Finding, shadow: bool, now: datetime) -> Signal:
    return Signal(
        strategy_version_id=version.id,
        rule_id=f.rule_id,
        rule_type=f.rule_type,
        subject=f.subject,
        ts=now,
        severity=f.severity,
        message=f.message,
        value=f.value,
        payload={
            **f.payload,
            "title": f.title,
            "push": f.push,
            "push_anonymous": f.push_anonymous,
        },
        dedup_key=f"s{version.strategy_id}:{f.dedup_key}",
        state="new",
        shadow=shadow,
    )
