"""What the strategy helper is told and shown (ADR 0048).

The same text serves both modes: the free one, where it is one prompt that the owner pastes into
claude.ai, and the in-app interview, where the rules go in the system prompt and the rest in the
first message. It holds the format of a strategy (generated from the schema, so it cannot drift
from what the app accepts), an example built from the owner's own groups, the holdings as shares
of the portfolio (no euro amounts), the owner's background notes and, when revising, the current
strategy.
"""

from __future__ import annotations

import typing
from datetime import date

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.agent.background import HelperNotes, helper_notes
from folio.agent.prompt_files import Prompt, load_prompt
from folio.db.models_analytics import Sleeve
from folio.db.models_ledger import Instrument
from folio.positions import load_positions
from folio.strategies import service
from folio.strategies.schema import Rule, StrategyDef
from folio.strategies.starter import starter_yaml

# What each rule does, in plain words, for the helper. A test keeps this in step with the schema.
RULE_HELP: dict[str, str] = {
    "drift_band": "warns when a group is further from its target share than its band allows",
    "trim_threshold": "warns when a group has grown above its trim threshold (time to take profit)",
    "concentration_limit": "warns when one company (or country) is too large across all funds",
    "drawdown": "warns when a holding (or the portfolio) is down this much from its peak",
    "price_move": "warns about a large move in a holding, in percent or in standard deviations",
    "price_level": "warns when one holding crosses a price",
    "macro_threshold": "warns when an economic series (like a real yield) passes a level or moves",
    "correlation_shift": "warns when a hedge stops moving against the assets it should protect",
    "contribution_due": "reminds a few days before the regular contribution is due",
    "cash_buffer": "warns when cash is outside the wanted range",
    "thesis_review_due": "reminds when it is time to re-read a written view on a holding or group",
    "stale_data": "warns when prices have stopped updating",
}


def _rule_models() -> list[type[BaseModel]]:
    union = typing.get_args(Rule)[0]
    return list(typing.get_args(union))


def _model_of(annotation: object) -> type[BaseModel]:
    """The model inside an annotation such as `list[Model]`, `Model | None` or `Model`."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    for arg in typing.get_args(annotation):
        if isinstance(arg, type) and issubclass(arg, BaseModel):
            return arg
    raise TypeError(f"no model in {annotation!r}")


def _fields(model: type[BaseModel], skip: tuple[str, ...] = ()) -> str:
    parts = []
    for name, field in model.model_fields.items():
        if name in skip:
            continue
        parts.append(f"{name}*" if field.is_required() else name)
    return ", ".join(parts)


def format_guide() -> str:
    """The strategy document in a few lines, from the schema. A star marks a required field."""
    lines = [
        "The document is YAML with one top-level key, `strategy`, with these fields "
        f"(* = required): {_fields(StrategyDef)}.",
        "- `sleeves` are the groups the investor holds things in. Each has: "
        f"{_fields(_model_of(StrategyDef.model_fields['sleeves'].annotation))}. "
        "`members` are ISINs from the holdings list. Targets and bands are in percent and "
        "percentage points; leave a number null until it is decided.",
        "- `risk_limits`: "
        + _fields(_model_of(StrategyDef.model_fields["risk_limits"].annotation))
        + ".",
        "- `contribution_plan` (leave out when the investor has none): "
        + _fields(_model_of(StrategyDef.model_fields["contribution_plan"].annotation))
        + ".",
        "- `principles` are short sentences in the investor's own words.",
        "- `rules` is a list; each has `id`, `type` and `severity` (info, low, medium, high, "
        "critical), plus these fields by type:",
    ]
    for model in _rule_models():
        kind = typing.get_args(model.model_fields["type"].annotation)[0]
        own = _fields(model, ("id", "type", "severity", "cooldown_days", "worsen_step", "enabled"))
        lines.append(f"  - {kind}: {own or 'no more fields'}. It {RULE_HELP.get(kind, '')}.")
    return "\n".join(lines)


def portfolio_text(db: Session, today: date) -> str:
    """What the investor holds as shares of the portfolio, and the groups with their targets.
    Never a euro amount."""
    rows, _ = load_positions(db, group_by_isin=True, today=today)
    sleeves = {s.id: s for s in db.scalars(select(Sleeve).where(Sleeve.deleted_at.is_(None)))}
    lines = ["Holdings (share of the portfolio):"]
    if not rows:
        lines.append("- none yet")
    for r in sorted(rows, key=lambda r: r.weight or 0, reverse=True):
        inst: Instrument = r.instrument
        share = "no price yet" if r.weight is None else f"{r.weight * 100:.1f}%"
        group = sleeves[inst.sleeve_id].name if inst.sleeve_id in sleeves else "no group yet"
        lines.append(
            f"- {inst.name} ({inst.isin or 'no ISIN'}, {inst.asset_class}): {share}; group: {group}"
        )
    lines.append("")
    lines.append("Groups (sleeves) as set up in the app now:")
    if not sleeves:
        lines.append("- none yet")
    for s in sorted(sleeves.values(), key=lambda s: (s.sort_order, s.id)):
        target = "no target" if s.target_pct is None else f"target {s.target_pct}%"
        band = "" if s.band_pct is None else f", band {s.band_pct} points"
        lines.append(f"- {s.name}: {target}{band}")
    return "\n".join(lines)


def example_yaml(db: Session) -> str:
    sleeves = []
    for s in db.scalars(
        select(Sleeve).where(Sleeve.deleted_at.is_(None)).order_by(Sleeve.sort_order, Sleeve.id)
    ):
        isins = db.scalars(
            select(Instrument.isin).where(
                Instrument.sleeve_id == s.id,
                Instrument.deleted_at.is_(None),
                Instrument.isin.is_not(None),
            )
        )
        sleeves.append((s.name, [i for i in isins if i]))
    return starter_yaml("My strategy", sleeves)


def context_text(
    db: Session, today: date, strategy_id: int | None = None, notes: HelperNotes | None = None
) -> str:
    """The format, an example, the holdings, the background notes and (to revise) the current
    strategy: everything the helper works from, apart from its own rules."""
    handed = notes if notes is not None else helper_notes(db)
    parts = [
        "## The format of a strategy\n" + format_guide(),
        "## An example, built from my own groups (every number left empty)\n```yaml\n"
        + example_yaml(db).rstrip()
        + "\n```",
        "## My portfolio now\n" + portfolio_text(db, today),
        "## What I wrote about myself\n"
        + (handed.text if handed.text else "Nothing yet: ask me about my goals first."),
    ]
    if strategy_id is not None:
        strategy = service.load(db, strategy_id)
        current = service.latest(db, strategy)
        parts.append(
            f"## The strategy to revise: {strategy.name} (it is {strategy.mode})\n```yaml\n"
            + current.yaml.rstrip()
            + "\n```"
        )
    return "\n\n".join(parts)


def paste_prompt(
    db: Session, today: date, strategy_id: int | None = None, draft_now: bool = False
) -> str:
    """One prompt for a chat on claude.ai (the free mode). With `draft_now` Claude is asked to
    draft the strategy from the notes straight away, without an interview first."""
    core: Prompt = load_prompt("strategist")
    wrapper: Prompt = load_prompt("strategist_paste")
    parts = [core.text, wrapper.text]
    if draft_now:
        parts.append(load_prompt("strategist_draft_now").text)
    parts.append(context_text(db, today, strategy_id))
    return "\n\n".join(parts)
