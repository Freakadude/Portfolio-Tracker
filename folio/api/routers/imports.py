import datetime as dt
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.db.models import Account
from folio.db.models_ledger import ImportBatch, ImportPreset
from folio.imports import service
from folio.imports.mapping import ImportMapping, detect_preset
from folio.imports.parse import MAX_BYTES, ParsedFile
from folio.imports.service import ImportProblem
from folio.ledger_service import TransactionError

router = APIRouter(tags=["imports"])

SAMPLE_ROWS = 15
MAX_ROWS_SHOWN = 500
MAX_ERRORS_SHOWN = 200


class BatchOut(BaseModel):
    id: int
    account_id: int
    file_name: str
    status: str
    rows_total: int
    rows_imported: int
    rows_skipped: int
    preset_id: int | None
    created_at: dt.datetime
    committed_at: dt.datetime | None
    errors: list[dict[str, Any]]


class HeaderOut(BaseModel):
    index: int
    label: str


class PreviewOut(BaseModel):
    batch: BatchOut
    encoding: str
    delimiter: str
    headers: list[HeaderOut]
    sample_rows: list[list[str]]
    row_count: int
    mapping: ImportMapping
    from_preset: bool
    detected_preset: str | None  # the broker the header row identifies, for example degiro


class RowOut(BaseModel):
    row: int
    status: str
    reason: str | None
    summary: dict[str, str] | None


class DryRunOut(BaseModel):
    batch_id: int
    counts: dict[str, int]
    unknown_isins: list[str]
    rows: list[RowOut]
    truncated: bool
    can_commit: bool


class MappingIn(BaseModel):
    mapping: ImportMapping
    save_as_preset: str | None = None


class CommitIn(BaseModel):
    skip_errors: bool = False


class PresetIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    mapping: ImportMapping


class PresetOut(BaseModel):
    id: int
    name: str
    mapping: ImportMapping


def _problem(exc: ImportProblem | TransactionError) -> ApiError:
    return ApiError(422, "Import problem", str(exc))


def _batch_out(batch: ImportBatch) -> BatchOut:
    return BatchOut(
        id=batch.id,
        account_id=batch.account_id,
        file_name=batch.file_name,
        status=batch.status,
        rows_total=batch.rows_total,
        rows_imported=batch.rows_imported,
        rows_skipped=batch.rows_skipped,
        preset_id=batch.preset_id,
        created_at=batch.created_at,
        committed_at=batch.committed_at,
        errors=list(batch.error_report or []),
    )


def _preview(
    batch: ImportBatch, parsed: ParsedFile, mapping: ImportMapping, from_preset: bool
) -> PreviewOut:
    return PreviewOut(
        batch=_batch_out(batch),
        encoding=parsed.encoding,
        delimiter=parsed.delimiter,
        headers=[HeaderOut(index=i, label=label) for i, label in enumerate(parsed.labels)],
        sample_rows=parsed.rows[:SAMPLE_ROWS],
        row_count=len(parsed.rows),
        mapping=mapping,
        from_preset=from_preset,
        detected_preset=detect_preset(parsed.headers),
    )


def _load(db: Session, batch_id: int) -> ImportBatch:
    try:
        return service.get_batch(db, batch_id)
    except ImportProblem as exc:
        raise ApiError(404, "Not found", str(exc)) from exc


@router.post("/imports", response_model=PreviewOut, status_code=201)
async def upload(
    _user: UserDep,
    db: DbDep,
    account_id: Annotated[int, Form()],
    file: Annotated[UploadFile, File()],
    preset_id: Annotated[int | None, Form()] = None,
) -> PreviewOut:
    account = db.get(Account, account_id)
    if account is None or account.deleted_at is not None:
        raise ApiError(422, "Import problem", "That account does not exist.")
    preset = db.get(ImportPreset, preset_id) if preset_id is not None else None
    if preset_id is not None and preset is None:
        raise ApiError(422, "Import problem", "That preset does not exist.")
    data = await file.read(MAX_BYTES + 1)
    try:
        batch, parsed, mapping = service.create_batch(
            db, account, file.filename or "import.csv", data, preset
        )
    except ImportProblem as exc:
        raise _problem(exc) from exc
    return _preview(batch, parsed, mapping, from_preset=preset is not None)


@router.get("/imports", response_model=list[BatchOut])
def history(_user: UserDep, db: DbDep) -> list[BatchOut]:
    batches = db.scalars(select(ImportBatch).order_by(ImportBatch.id.desc()).limit(200))
    return [_batch_out(b) for b in batches]


@router.get("/imports/{batch_id}", response_model=PreviewOut)
def read(batch_id: int, _user: UserDep, db: DbDep) -> PreviewOut:
    batch = _load(db, batch_id)
    if batch.status != "preview":
        raise ApiError(409, "Already committed", "This import was already committed.")
    try:
        parsed = service.load_parsed(batch)
    except ImportProblem as exc:
        raise _problem(exc) from exc
    return _preview(
        batch, parsed, service.load_mapping(batch), from_preset=batch.preset_id is not None
    )


@router.put("/imports/{batch_id}/mapping", response_model=DryRunOut)
def set_mapping(batch_id: int, body: MappingIn, _user: UserDep, db: DbDep) -> DryRunOut:
    """Save the column mapping and return the dry run: what would be imported, nothing written."""
    batch = _load(db, batch_id)
    try:
        service.set_mapping(db, batch, body.mapping)
        if body.save_as_preset:
            service.save_preset(db, body.save_as_preset, body.mapping)
        return _dry_run_out(batch, service.dry_run(db, batch))
    except ImportProblem as exc:
        raise _problem(exc) from exc


@router.get("/imports/{batch_id}/dry-run", response_model=DryRunOut)
def dry_run(batch_id: int, _user: UserDep, db: DbDep) -> DryRunOut:
    batch = _load(db, batch_id)
    try:
        return _dry_run_out(batch, service.dry_run(db, batch))
    except ImportProblem as exc:
        raise _problem(exc) from exc


def _dry_run_out(batch: ImportBatch, result: service.DryRun) -> DryRunOut:
    errors = [r for r in result.rows if r.status == "error"][:MAX_ERRORS_SHOWN]
    others = [r for r in result.rows if r.status != "error"]
    shown = sorted(
        [*errors, *others[: max(0, MAX_ROWS_SHOWN - len(errors))]], key=lambda r: r.row_number
    )
    counts = result.counts()
    return DryRunOut(
        batch_id=batch.id,
        counts=counts,
        unknown_isins=result.unknown_isins,
        rows=[
            RowOut(row=r.row_number, status=r.status, reason=r.reason, summary=r.summary)
            for r in shown
        ],
        truncated=len(shown) < len(result.rows),
        can_commit=counts["new"] > 0 and counts["error"] == 0,
    )


@router.post("/imports/{batch_id}/commit", response_model=BatchOut)
def commit(batch_id: int, body: CommitIn, _user: UserDep, db: DbDep) -> BatchOut:
    batch = _load(db, batch_id)
    try:
        return _batch_out(service.commit(db, batch, skip_errors=body.skip_errors))
    except (ImportProblem, TransactionError) as exc:
        raise _problem(exc) from exc


@router.delete("/imports/{batch_id}", status_code=204)
def undo(batch_id: int, _user: UserDep, db: DbDep) -> None:
    """Discard a preview, or undo a committed import: all its transactions are removed."""
    batch = _load(db, batch_id)
    try:
        service.undo(db, batch)
    except (ImportProblem, TransactionError) as exc:
        raise _problem(exc) from exc


# --- presets ------------------------------------------------------------------------------------


@router.get("/import-presets", response_model=list[PresetOut])
def list_presets(_user: UserDep, db: DbDep) -> list[PresetOut]:
    presets = db.scalars(select(ImportPreset).order_by(ImportPreset.name))
    return [
        PresetOut(id=p.id, name=p.name, mapping=ImportMapping.model_validate(p.config))
        for p in presets
    ]


@router.post("/import-presets", response_model=PresetOut, status_code=201)
def create_preset(body: PresetIn, _user: UserDep, db: DbDep) -> PresetOut:
    try:
        preset = service.save_preset(db, body.name, body.mapping)
    except ImportProblem as exc:
        raise _problem(exc) from exc
    return PresetOut(id=preset.id, name=preset.name, mapping=body.mapping)


@router.delete("/import-presets/{preset_id}", status_code=204)
def delete_preset(preset_id: int, _user: UserDep, db: DbDep) -> None:
    preset = db.get(ImportPreset, preset_id)
    if preset is None:
        raise ApiError(404, "Not found", "That preset does not exist.")
    db.execute(update(ImportBatch).where(ImportBatch.preset_id == preset_id).values(preset_id=None))
    db.delete(preset)
