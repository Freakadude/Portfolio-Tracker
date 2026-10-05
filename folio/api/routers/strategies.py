"""Strategies (FR-ST-01, FR-ST-02): YAML or form, immutable versions, diffs, active and shadow."""

import datetime as dt
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.db.models_analytics import Sleeve
from folio.db.models_ledger import Instrument
from folio.db.models_strategy import Strategy, StrategyVersion
from folio.strategies import service
from folio.strategies.diff import side_by_side
from folio.strategies.parse import Problem, StrategyError, to_json
from folio.strategies.schema import StrategyDocument
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
