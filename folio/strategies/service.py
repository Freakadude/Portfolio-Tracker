"""Strategies in the database: immutable versions, one active strategy, shadow strategies, and
the sleeve targets that follow the active strategy (ADR 0020)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from folio.audit import write_audit
from folio.db.base import utcnow
from folio.db.models_analytics import Sleeve
from folio.db.models_ledger import Instrument
from folio.db.models_strategy import Strategy, StrategyVersion
from folio.strategies.parse import from_definition, parse, to_json, to_yaml
from folio.strategies.schema import StrategyDef, is_isin

MODES = ("active", "shadow", "off")


class StrategyNotFound(LookupError):
    pass


@dataclass(frozen=True)
class Parsed:
    strategy: StrategyDef
    yaml: str


def read_input(yaml_text: str | None, definition: dict[str, Any] | None) -> Parsed:
    """A strategy as the editor sends it: raw YAML (kept as written, comments included) or the
    form's JSON (written out as canonical YAML). Raises StrategyError."""
    if yaml_text is not None:
        return Parsed(parse(yaml_text), yaml_text)
    strategy = from_definition(definition or {})
    return Parsed(strategy, to_yaml(strategy))


def load(db: Session, strategy_id: int) -> Strategy:
    found = db.get(Strategy, strategy_id)
    if found is None or found.deleted_at is not None:
        raise StrategyNotFound(strategy_id)
    return found


def latest(db: Session, strategy: Strategy) -> StrategyVersion:
    version = db.scalars(
        select(StrategyVersion)
        .where(StrategyVersion.strategy_id == strategy.id)
        .order_by(StrategyVersion.version.desc())
        .limit(1)
    ).first()
    if version is None:  # every strategy is created with a first version
        raise StrategyNotFound(strategy.id)
    return version


def version(db: Session, strategy: Strategy, number: int) -> StrategyVersion:
    found = db.scalar(
        select(StrategyVersion).where(
            StrategyVersion.strategy_id == strategy.id, StrategyVersion.version == number
        )
    )
    if found is None:
        raise StrategyNotFound(strategy.id)
    return found


def versions(db: Session, strategy: Strategy) -> list[StrategyVersion]:
    return list(
        db.scalars(
            select(StrategyVersion)
            .where(StrategyVersion.strategy_id == strategy.id)
            .order_by(StrategyVersion.version.desc())
        )
    )


def create(db: Session, parsed: Parsed, note: str | None = None, actor: str = "user") -> Strategy:
    strategy = Strategy(name=parsed.strategy.name, mode="off")
    db.add(strategy)
    db.flush()
    _add_version(db, strategy, parsed, note, 1)
    write_audit(
        db, actor, "strategy", "create", entity_id=strategy.id, diff={"name": strategy.name}
    )
    return strategy


def save(
    db: Session, strategy: Strategy, parsed: Parsed, note: str | None = None, actor: str = "user"
) -> StrategyVersion:
    """Add a version; the earlier ones are never changed. An active strategy's sleeves are
    synced straight away."""
    number = (
        db.scalar(
            select(func.max(StrategyVersion.version)).where(
                StrategyVersion.strategy_id == strategy.id
            )
        )
        or 0
    ) + 1
    added = _add_version(db, strategy, parsed, note, number)
    old_name, strategy.name = strategy.name, parsed.strategy.name
    write_audit(
        db,
        actor,
        "strategy",
        "save",
        entity_id=strategy.id,
        diff={
            "version": number,
            **(
                {"name": {"old": old_name, "new": strategy.name}}
                if old_name != strategy.name
                else {}
            ),
        },
    )
    if strategy.mode == "active":
        sync_sleeves(db, parsed.strategy, actor)
    return added


def _add_version(
    db: Session, strategy: Strategy, parsed: Parsed, note: str | None, number: int
) -> StrategyVersion:
    row = StrategyVersion(
        strategy_id=strategy.id,
        version=number,
        yaml=parsed.yaml,
        definition=to_json(parsed.strategy),
        note=note,
    )
    db.add(row)
    db.flush()
    return row


def set_mode(db: Session, strategy: Strategy, mode: str, actor: str = "user") -> list[Strategy]:
    """Change a strategy's mode. Making one active turns the previously active one into a
    shadow (only one strategy is active, FR-ST-02). Returns every strategy that changed."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    changed: list[Strategy] = []
    if mode == "active":
        for other in db.scalars(
            select(Strategy).where(
                Strategy.mode == "active", Strategy.id != strategy.id, Strategy.deleted_at.is_(None)
            )
        ):
            other.mode = "shadow"
            changed.append(other)
            write_audit(db, actor, "strategy", "mode", entity_id=other.id,
                        diff={"mode": {"old": "active", "new": "shadow"}})  # fmt: skip
    if strategy.mode != mode:
        write_audit(db, actor, "strategy", "mode", entity_id=strategy.id,
                    diff={"mode": {"old": strategy.mode, "new": mode}})  # fmt: skip
        strategy.mode = mode
        changed.append(strategy)
    if mode == "active":
        sync_sleeves(db, active_definition(db, strategy), actor)
    elif not active_strategies(db):
        release_sleeves(db, actor)
    db.flush()
    return changed


def delete(db: Session, strategy: Strategy, actor: str = "user") -> None:
    was_active = strategy.mode == "active"
    strategy.deleted_at, strategy.mode = utcnow(), "off"
    write_audit(
        db, actor, "strategy", "delete", entity_id=strategy.id, diff={"name": strategy.name}
    )
    if was_active:
        release_sleeves(db, actor)


def active_strategies(db: Session) -> list[Strategy]:
    return list(
        db.scalars(select(Strategy).where(Strategy.mode == "active", Strategy.deleted_at.is_(None)))
    )


def active_definition(db: Session, strategy: Strategy) -> StrategyDef:
    return StrategyDef.model_validate(latest(db, strategy).definition)


def running(db: Session) -> list[tuple[Strategy, StrategyVersion, StrategyDef]]:
    """The strategies the rules engine evaluates: the active one and every shadow."""
    out = []
    for s in db.scalars(
        select(Strategy)
        .where(Strategy.mode.in_(("active", "shadow")), Strategy.deleted_at.is_(None))
        .order_by(Strategy.id)
    ):
        v = latest(db, s)
        out.append((s, v, StrategyDef.model_validate(v.definition)))
    return out


# --- sleeves follow the active strategy --------------------------------------------------------


def managing_strategy(db: Session) -> Strategy | None:
    found = active_strategies(db)
    return found[0] if found else None


def sync_sleeves(db: Session, strategy: StrategyDef, actor: str = "user") -> None:
    """Make the sleeve table match the active strategy: its sleeves exist with its targets and
    soft bands, in its order, and listed members are assigned to them. Sleeves the strategy does
    not mention keep their instruments but lose their targets, so no stale drift shows."""
    sleeves = {
        s.name.lower(): s for s in db.scalars(select(Sleeve).where(Sleeve.deleted_at.is_(None)))
    }
    named: set[int] = set()
    changes: dict[str, Any] = {}
    instruments = list(db.scalars(select(Instrument).where(Instrument.deleted_at.is_(None))))
    for order, spec in enumerate(strategy.sleeves, start=1):
        row = sleeves.get(spec.id.lower())
        if row is None:
            row = Sleeve(name=spec.id)
            db.add(row)
            db.flush()
            changes[spec.id] = "created"
        target, band = spec.target_pct, spec.soft_band_pp
        if (row.target_pct, row.band_pct, row.sort_order) != (target, band, order):
            changes.setdefault(spec.id, {"target_pct": str(target), "band_pct": str(band)})
        row.target_pct, row.band_pct, row.sort_order = target, band, order
        named.add(row.id)
        for member in spec.members:
            for instrument in instruments:
                hit = (
                    instrument.isin == member
                    if is_isin(member)
                    else member in (instrument.tags or [])
                )
                if hit and instrument.sleeve_id != row.id:
                    instrument.sleeve_id = row.id
                    changes.setdefault("members", []).append(f"{instrument.name} -> {spec.id}")
    for row in sleeves.values():
        if row.id not in named and (row.target_pct is not None or row.band_pct is not None):
            row.target_pct = row.band_pct = None
            changes[row.name] = "targets cleared"
    db.flush()
    if changes:
        write_audit(db, actor, "sleeve", "sync", diff=changes)


def release_sleeves(db: Session, actor: str = "user") -> None:
    """No strategy is active any more: the sleeves keep their targets, editable again."""
    write_audit(db, actor, "sleeve", "release", diff={"managed_by": None})
