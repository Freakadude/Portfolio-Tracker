"""The CSV import workflow (FR-TX-07): upload, map, dry run, commit, undo.

A batch holds the uploaded file and the mapping until it is committed; committing posts every
new row in one database transaction, rebuilds the account once, and drops the raw upload.
Re-importing the same file adds nothing: each row has a stable key stored as `external_ref`.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.audit import write_audit
from folio.db.base import utcnow
from folio.db.models import Account
from folio.db.models_ledger import ImportBatch, ImportPreset, Instrument, LedgerTransaction
from folio.domain import CostBasisMethod, OversellError, rebuild
from folio.imports.mapping import ConvertedRow, ImportMapping, convert_row, suggest_mapping
from folio.imports.parse import ParsedFile, ParseError, parse_csv
from folio.ledger_service import (
    TransactionError,
    account_transactions,
    fields_to_txin,
    insert_transaction,
    normalize,
    rebuild_after_bulk,
    to_txin,
)

_NEEDS_INSTRUMENT = {"buy", "sell", "dividend", "split", "transfer_in", "transfer_out"}


class ImportProblem(ValueError):
    """The import cannot continue; the message is for the owner."""


@dataclass
class RowResult:
    row_number: int
    status: str  # new | duplicate | error | skipped
    reason: str | None = None
    summary: dict[str, str] | None = None
    fields: dict[str, Any] | None = None
    ref: str | None = None


@dataclass
class DryRun:
    rows: list[RowResult] = field(default_factory=list)
    unknown_isins: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out = {"new": 0, "duplicate": 0, "error": 0, "skipped": 0}
        for row in self.rows:
            out[row.status] += 1
        return out


# --- batches ------------------------------------------------------------------------------------


def create_batch(
    db: Session, account: Account, file_name: str, data: bytes, preset: ImportPreset | None
) -> tuple[ImportBatch, ParsedFile, ImportMapping]:
    try:
        parsed = parse_csv(data)
    except ParseError as exc:
        raise ImportProblem(str(exc)) from exc
    mapping = (
        ImportMapping.model_validate(preset.config)
        if preset is not None
        else suggest_mapping(parsed)
    )
    batch = ImportBatch(
        account_id=account.id,
        file_name=file_name[:255],
        preset_id=preset.id if preset else None,
        rows_total=len(parsed.rows),
        status="preview",
        config={
            "raw": base64.b64encode(data).decode("ascii"),
            "mapping": mapping.model_dump(mode="json"),
            "encoding": parsed.encoding,
            "delimiter": parsed.delimiter,
        },
    )
    db.add(batch)
    db.flush()
    return batch, parsed, mapping


def get_batch(db: Session, batch_id: int) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise ImportProblem("That import does not exist.")
    return batch


def load_parsed(batch: ImportBatch) -> ParsedFile:
    raw = (batch.config or {}).get("raw")
    if not raw:
        raise ImportProblem("The uploaded file is no longer stored; upload it again.")
    return parse_csv(base64.b64decode(raw))


def load_mapping(batch: ImportBatch) -> ImportMapping:
    return ImportMapping.model_validate((batch.config or {}).get("mapping") or {})


def set_mapping(db: Session, batch: ImportBatch, mapping: ImportMapping) -> None:
    if batch.status != "preview":
        raise ImportProblem("This import was already committed, so its mapping cannot change.")
    batch.config = {**(batch.config or {}), "mapping": mapping.model_dump(mode="json")}
    db.flush()


# --- dry run ------------------------------------------------------------------------------------


def _existing_refs(db: Session, account_id: int, refs: list[str]) -> set[str]:
    found: set[str] = set()
    for start in range(0, len(refs), 500):  # stay below SQLite's variable limit
        chunk = refs[start : start + 500]
        found.update(
            db.scalars(
                select(LedgerTransaction.external_ref).where(
                    LedgerTransaction.account_id == account_id,
                    LedgerTransaction.deleted_at.is_(None),
                    LedgerTransaction.external_ref.in_(chunk),
                )
            )
        )
    return found


def dry_run(db: Session, batch: ImportBatch) -> DryRun:
    """Classify every row as new, duplicate, error or skipped, without writing anything."""
    account = db.get(Account, batch.account_id)
    if account is None:
        raise ImportProblem("The account of this import no longer exists.")
    parsed, mapping = load_parsed(batch), load_mapping(batch)
    isins = {
        i.isin: i
        for i in db.scalars(
            select(Instrument).where(Instrument.deleted_at.is_(None), Instrument.isin.is_not(None))
        )
    }

    converted: list[ConvertedRow] = [
        convert_row(number, cells, mapping, account.id)
        for number, cells in zip(parsed.row_numbers, parsed.rows, strict=True)
    ]
    results: list[RowResult] = []
    unknown: list[str] = []
    seen: dict[str, int] = {}
    for row in converted:
        if row.status == "skipped":
            results.append(RowResult(row.row_number, "skipped", row.reason, row.summary))
            continue
        if row.status == "error" or row.tx is None or row.ref is None:
            results.append(RowResult(row.row_number, "error", row.reason, row.summary))
            continue
        tx = row.tx
        instrument = isins.get(row.isin) if row.isin else None
        if tx.type in _NEEDS_INSTRUMENT and instrument is None:
            reason = (
                f"{row.isin} is not added yet. Add the instrument first."
                if row.isin
                else f"A {tx.type.replace('_', ' ')} needs an ISIN."
            )
            if row.isin and row.isin not in unknown:
                unknown.append(row.isin)
            results.append(RowResult(row.row_number, "error", reason, row.summary))
            continue
        if instrument is not None:
            tx = tx.model_copy(update={"instrument_id": instrument.id})
        seen[row.ref] = seen.get(row.ref, 0) + 1
        ref = f"{row.ref}#{seen[row.ref]}"
        try:
            fields = normalize(db, tx)
        except TransactionError as exc:
            reason = "; ".join(message for _, message in exc.errors) or str(exc)
            results.append(RowResult(row.row_number, "error", reason, row.summary))
            continue
        results.append(RowResult(row.row_number, "new", None, row.summary, fields, ref))

    duplicates = _existing_refs(db, account.id, [r.ref for r in results if r.ref])
    for r in results:
        if r.status == "new" and r.ref in duplicates:
            r.status, r.fields = "duplicate", None
    _reject_oversells(db, account, results)
    return DryRun(results, unknown)


def _reject_oversells(db: Session, account: Account, results: list[RowResult]) -> None:
    """Replay the account's history plus the new rows; a row that would sell more than is held
    becomes an error row (and so do later rows that depended on it)."""
    history = [to_txin(r) for r in account_transactions(db, account.id)]
    method = CostBasisMethod(account.cost_basis_method)
    for _ in range(200):
        pending = {r.row_number: r for r in results if r.status == "new" and r.fields}
        if not pending:
            return
        candidates = [fields_to_txin(-number, r.fields or {}) for number, r in pending.items()]
        try:
            rebuild([*history, *candidates], method)
            return
        except OversellError as exc:
            culprit = pending.get(-exc.tx_id)
            if culprit is None:  # an existing transaction already breaks the ledger
                return
            culprit.status, culprit.reason, culprit.fields = "error", str(exc), None


# --- commit and undo ----------------------------------------------------------------------------


def commit(
    db: Session, batch: ImportBatch, *, skip_errors: bool = False, actor: str = "user"
) -> ImportBatch:
    if batch.status != "preview":
        raise ImportProblem("This import was already committed.")
    account = db.get(Account, batch.account_id)
    if account is None:
        raise ImportProblem("The account of this import no longer exists.")
    result = dry_run(db, batch)
    errors = [r for r in result.rows if r.status == "error"]
    if errors and not skip_errors:
        raise ImportProblem(
            f"{len(errors)} row{'s' if len(errors) != 1 else ''} cannot be imported. "
            "Fix the mapping or add the missing instruments, or import the valid rows only."
        )
    new = [r for r in result.rows if r.status == "new" and r.fields is not None]
    if not new:
        raise ImportProblem("There is nothing new to import.")
    earliest: date | None = None
    for row in new:
        if row.fields is None:  # filtered above; keeps the type checker honest
            continue
        insert_transaction(
            db, row.fields, source="import", external_ref=row.ref, import_batch_id=batch.id
        )
        day = row.fields["trade_date"]
        earliest = day if earliest is None or day < earliest else earliest
    rebuild_after_bulk(
        db, account, earliest, actor
    )  # one rebuild; rolls back everything on failure

    counts = result.counts()
    batch.rows_total = len(result.rows)
    batch.rows_imported = len(new)
    batch.rows_skipped = counts["duplicate"] + counts["skipped"] + len(errors)
    batch.error_report = [{"row": r.row_number, "reason": r.reason} for r in errors]
    batch.status = "committed"
    batch.committed_at = utcnow()
    batch.config = {k: v for k, v in (batch.config or {}).items() if k != "raw"}  # drop the upload
    db.flush()
    write_audit(
        db,
        actor,
        "import_batch",
        "commit",
        entity_id=batch.id,
        diff={
            "file": batch.file_name,
            "account_id": batch.account_id,
            "imported": len(new),
            "duplicates": counts["duplicate"],
            "errors": len(errors),
        },
    )
    return batch


def undo(db: Session, batch: ImportBatch, actor: str = "user") -> None:
    """Remove a batch: a preview is discarded; a committed one has all its transactions deleted
    and the account rebuilt. Refused if later transactions depend on the imported ones."""
    if batch.status == "undone":
        raise ImportProblem("This import was already undone.")
    if batch.status == "preview":
        db.delete(batch)
        db.flush()
        return
    account = db.get(Account, batch.account_id)
    if account is None:
        raise ImportProblem("The account of this import no longer exists.")
    rows = list(
        db.scalars(
            select(LedgerTransaction).where(
                LedgerTransaction.import_batch_id == batch.id,
                LedgerTransaction.deleted_at.is_(None),
            )
        )
    )
    now = utcnow()
    for row in rows:
        row.deleted_at = now
    db.flush()
    earliest = min((r.trade_date for r in rows), default=None)
    try:
        rebuild_after_bulk(db, account, earliest, actor)
    except TransactionError as exc:
        raise ImportProblem(f"Cannot undo this import: {exc}") from exc
    batch.status = "undone"
    db.flush()
    write_audit(
        db, actor, "import_batch", "undo", entity_id=batch.id,
        diff={"file": batch.file_name, "removed": len(rows)},
    )  # fmt: skip


# --- presets ------------------------------------------------------------------------------------


def save_preset(db: Session, name: str, mapping: ImportMapping) -> ImportPreset:
    name = name.strip()
    if not name:
        raise ImportProblem("Give the preset a name.")
    preset = db.scalar(select(ImportPreset).where(ImportPreset.name == name))
    if preset is None:
        preset = ImportPreset(name=name, config=mapping.model_dump(mode="json"))
        db.add(preset)
    else:
        preset.config = mapping.model_dump(mode="json")
    db.flush()
    return preset
