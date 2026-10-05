"""Strategies (FR-ST-01, FR-ST-02): YAML or form, immutable versions, diffs, active and shadow."""

import datetime as dt
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.db.models_analytics import Sleeve
from folio.db.models_ledger import Instrument
from folio.db.models_strategy import Signal, Strategy, StrategyVersion
from folio.jobs.requests import request_rules
from folio.strategies import service
from folio.strategies.diff import side_by_side
from folio.strategies.inputs import build
from folio.strategies.parse import Problem, StrategyError, to_json
from folio.strategies.rules import evaluate
from folio.strategies.schema import StrategyDef, StrategyDocument
from folio.strategies.starter import starter_yaml

router = APIRouter(prefix="/strategies", tags=["strategies"])


class StrategyInput(BaseModel):
    """The YAML text (kept as written) or the form's JSON (written out as YAML)."""

    model_config = ConfigDict(extra="forbid")

    yaml: str | None = Field(default=None, max_length=200_000)
    definition: dict[str, Any] | None = None
    note: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _one(self) -> "StrategyInput":
        if (self.yaml is None) == (self.definition is None):
            raise ValueError("Send either yaml or definition.")
        return self


class ProblemOut(BaseModel):
    line: int | None
    path: str
    message: str


class VersionSummary(BaseModel):
    version: int
    created_at: dt.datetime
    note: str | None


class VersionOut(VersionSummary):
    yaml: str
    definition: dict[str, Any]


class StrategySummary(BaseModel):
    id: int
    name: str
    mode: str
    version: int
    updated_at: dt.datetime


class StrategyOut(BaseModel):
    id: int
    name: str
    mode: str
    current: VersionOut
    versions: list[VersionSummary]


class CheckOut(BaseModel):
    ok: bool
    problems: list[ProblemOut]
    yaml: str | None
    definition: dict[str, Any] | None


class StarterOut(BaseModel):
    yaml: str
    definition: dict[str, Any]


class DiffRowOut(BaseModel):
    kind: str
    old_line: int | None
    old_text: str | None
    new_line: int | None
    new_text: str | None


class DiffOut(BaseModel):
    old_version: int
    new_version: int
    rows: list[DiffRowOut]


class ModeIn(BaseModel):
    mode: Literal["active", "shadow", "off"]


def _problems(problems: list[Problem]) -> list[dict[str, Any]]:
    return [{"line": p.line, "path": p.path, "message": p.message} for p in problems]


def _invalid(exc: StrategyError) -> ApiError:
    return ApiError(
        422,
        "Invalid strategy",
        str(exc),
        errors=[{"field": p.path, "message": p.message} for p in exc.problems],
        problems=_problems(exc.problems),
    )


def _parsed(body: StrategyInput) -> service.Parsed:
    try:
        return service.read_input(body.yaml, body.definition)
    except StrategyError as exc:
        raise _invalid(exc) from exc


def _load(db: Session, strategy_id: int) -> Strategy:
    try:
        return service.load(db, strategy_id)
    except service.StrategyNotFound:
        raise ApiError(404, "Not found", "That strategy does not exist.") from None


def _version_out(v: StrategyVersion) -> VersionOut:
    return VersionOut(
        version=v.version,
        created_at=v.created_at,
        note=v.note,
        yaml=v.yaml,
        definition=v.definition,
    )


def _out(db: Session, strategy: Strategy) -> StrategyOut:
    return StrategyOut(
        id=strategy.id,
        name=strategy.name,
        mode=strategy.mode,
        current=_version_out(service.latest(db, strategy)),
        versions=[
            VersionSummary(version=v.version, created_at=v.created_at, note=v.note)
            for v in service.versions(db, strategy)
        ],
    )


@router.get("", response_model=list[StrategySummary])
def list_strategies(_user: UserDep, db: DbDep) -> list[StrategySummary]:
    rows = db.scalars(select(Strategy).where(Strategy.deleted_at.is_(None)).order_by(Strategy.id))
    out = []
    for s in rows:
        v = service.latest(db, s)
        out.append(
            StrategySummary(
                id=s.id, name=s.name, mode=s.mode, version=v.version, updated_at=v.created_at
            )
        )
    return out


@router.get("/starter", response_model=StarterOut)
def starter(_user: UserDep, db: DbDep) -> StarterOut:
    """A new strategy built from your sleeves, every target left empty (Q3)."""
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
    count = (
        db.scalar(select(func.count()).select_from(Strategy).where(Strategy.deleted_at.is_(None)))
        or 0
    )
    text = starter_yaml("My strategy" if count == 0 else f"Strategy {count + 1}", sleeves)
    parsed = service.read_input(text, None)
    return StarterOut(yaml=text, definition=to_json(parsed.strategy))


@router.get("/schema")
def json_schema(_user: UserDep) -> dict[str, Any]:
    """The JSON Schema of the strategy document, for the form view and editors."""
    return StrategyDocument.model_json_schema()


@router.post("/check", response_model=CheckOut)
def check(body: StrategyInput, _user: UserDep) -> CheckOut:
    """Validate without saving; returns both forms so the editor can switch views."""
    try:
        parsed = service.read_input(body.yaml, body.definition)
    except StrategyError as exc:
        return CheckOut(
            ok=False,
            problems=[ProblemOut(**p) for p in _problems(exc.problems)],
            yaml=None,
            definition=None,
        )
    return CheckOut(ok=True, problems=[], yaml=parsed.yaml, definition=to_json(parsed.strategy))


@router.post("", response_model=StrategyOut, status_code=201)
def create(body: StrategyInput, _user: UserDep, db: DbDep) -> StrategyOut:
    strategy = service.create(db, _parsed(body), body.note)
    return _out(db, strategy)


class SignalOut(BaseModel):
    id: int
    strategy_id: int | None
    strategy_name: str | None
    version: int | None
    rule_id: str
    rule_type: str
    subject: str
    ts: dt.datetime
    severity: str
    title: str
    message: str
    value: Decimal | None
    state: str
    shadow: bool


class RuleStatusOut(BaseModel):
    rule_id: str
    rule_type: str
    ready: bool
    reason: str | None


class SleeveNowOut(BaseModel):
    id: str
    weight: Decimal
    target: Decimal | None
    soft_band_pp: Decimal | None
    hard_band_pp: Decimal | None


class StatusOut(BaseModel):
    rules: list[RuleStatusOut]
    sleeves: list[SleeveNowOut]
    conditions_true: int


@router.get("/signals", response_model=list[SignalOut])
def list_signals(
    _user: UserDep,
    db: DbDep,
    strategy_id: int | None = None,
    shadow: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[SignalOut]:
    """Signals, newest first. Shadow signals appear only here, never in the inbox (FR-ST-02)."""
    query = (
        select(Signal, StrategyVersion, Strategy)
        .join(StrategyVersion, StrategyVersion.id == Signal.strategy_version_id, isouter=True)
        .join(Strategy, Strategy.id == StrategyVersion.strategy_id, isouter=True)
        .order_by(Signal.ts.desc(), Signal.id.desc())
        .limit(limit)
    )
    if strategy_id is not None:
        query = query.where(StrategyVersion.strategy_id == strategy_id)
    if shadow is not None:
        query = query.where(Signal.shadow.is_(shadow))
    return [
        SignalOut(
            id=sig.id,
            strategy_id=None if strat is None else strat.id,
            strategy_name=None if strat is None else strat.name,
            version=None if ver is None else ver.version,
            rule_id=sig.rule_id,
            rule_type=sig.rule_type,
            subject=sig.subject,
            ts=sig.ts,
            severity=sig.severity,
            title=str((sig.payload or {}).get("title") or sig.message),
            message=sig.message,
            value=sig.value,
            state=sig.state,
            shadow=sig.shadow,
        )
        for sig, ver, strat in db.execute(query)
    ]


@router.post("/run", status_code=202)
def run_now(_user: UserDep, db: DbDep) -> dict[str, str]:
    """Check the rules now; the worker picks the request up within seconds."""
    request_rules(db)
    return {"status": "queued"}


@router.get("/{strategy_id}", response_model=StrategyOut)
def get_strategy(strategy_id: int, _user: UserDep, db: DbDep) -> StrategyOut:
    return _out(db, _load(db, strategy_id))


@router.post("/{strategy_id}/versions", response_model=StrategyOut, status_code=201)
def save_version(strategy_id: int, body: StrategyInput, _user: UserDep, db: DbDep) -> StrategyOut:
    """Save a new version. Earlier versions never change (FR-ST-01)."""
    strategy = _load(db, strategy_id)
    service.save(db, strategy, _parsed(body), body.note)
    return _out(db, strategy)


@router.get("/{strategy_id}/versions/{number}", response_model=VersionOut)
def get_version(strategy_id: int, number: int, _user: UserDep, db: DbDep) -> VersionOut:
    strategy = _load(db, strategy_id)
    try:
        return _version_out(service.version(db, strategy, number))
    except service.StrategyNotFound:
        raise ApiError(404, "Not found", "That version does not exist.") from None


@router.get("/{strategy_id}/diff", response_model=DiffOut)
def diff(strategy_id: int, old: int, new: int, _user: UserDep, db: DbDep) -> DiffOut:
    strategy = _load(db, strategy_id)
    try:
        a, b = service.version(db, strategy, old), service.version(db, strategy, new)
    except service.StrategyNotFound:
        raise ApiError(404, "Not found", "That version does not exist.") from None
    rows = side_by_side(a.yaml, b.yaml)
    return DiffOut(
        old_version=old,
        new_version=new,
        rows=[
            DiffRowOut(
                kind=r.kind,
                old_line=r.old_line,
                old_text=r.old_text,
                new_line=r.new_line,
                new_text=r.new_text,
            )
            for r in rows
        ],
    )


@router.post("/{strategy_id}/mode", response_model=list[StrategySummary])
def set_mode(strategy_id: int, body: ModeIn, _user: UserDep, db: DbDep) -> list[StrategySummary]:
    """Activate, shadow or switch off. Activating one makes the previous active one a shadow
    (FR-ST-02) and syncs the sleeve targets."""
    strategy = _load(db, strategy_id)
    service.set_mode(db, strategy, body.mode)
    return list_strategies(_user, db)


@router.delete("/{strategy_id}", status_code=204)
def delete(strategy_id: int, _user: UserDep, db: DbDep) -> None:
    service.delete(db, _load(db, strategy_id))


@router.get("/{strategy_id}/status", response_model=StatusOut)
def rule_status(strategy_id: int, _user: UserDep, db: DbDep) -> StatusOut:
    """Which rules can fire and which are waiting (for a target, a band, data), and where each
    sleeve stands now against the latest version."""
    strategy = _load(db, strategy_id)
    version = service.latest(db, strategy)
    definition = StrategyDef.model_validate(version.definition)
    today = dt.date.today()
    inputs = build(db, definition, today, version.created_at.date())
    evaluation = evaluate(definition, inputs)
    return StatusOut(
        rules=[
            RuleStatusOut(rule_id=r.rule_id, rule_type=r.rule_type, ready=r.ready, reason=r.reason)
            for r in evaluation.statuses
        ],
        sleeves=[
            SleeveNowOut(
                id=spec.id,
                weight=inputs.sleeves[spec.id].weight,
                target=spec.target_pct,
                soft_band_pp=spec.soft_band_pp,
                hard_band_pp=spec.hard_band_pp,
            )
            for spec in definition.sleeves
        ],
        conditions_true=len(evaluation.findings),
    )
