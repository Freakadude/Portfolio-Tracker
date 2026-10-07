"""The strategy helper: the owner's background notes (ADR 0048).

The notes are what the helper is told about the owner. They are kept locally, are included in the
backups, and are given to nothing but the strategy helper.
"""

import datetime as dt
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.agent.background import NOTE_LIMIT, SOURCES, TOTAL_LIMIT, helper_notes
from folio.agent.prompt_files import load_prompt
from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.audit import write_audit
from folio.db.models_insight import BackgroundNote

router = APIRouter(prefix="/assistant", tags=["assistant"])

Source = Literal["written", "pasted", "chat_export"]


class NoteOut(BaseModel):
    id: int
    title: str
    body: str
    source: str
    use_in_helper: bool
    characters: int
    created_at: dt.datetime
    updated_at: dt.datetime


class NotesOut(BaseModel):
    notes: list[NoteOut]
    note_limit: int  # characters in one note
    total_limit: int  # characters of notes the helper is given in all
    used: int  # characters the helper is given now
    left_out: int  # switched-on notes that do not fit under the total limit


class NoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1)
    source: Source = "written"
    use_in_helper: bool = True


class NoteChanges(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=120)
    body: str | None = Field(default=None, min_length=1)
    use_in_helper: bool | None = None


class PromptOut(BaseModel):
    text: str


def _out(note: BackgroundNote) -> NoteOut:
    return NoteOut(
        id=note.id,
        title=note.title,
        body=note.body,
        source=note.source,
        use_in_helper=note.use_in_helper,
        characters=len(note.body),
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


def _load(db: Session, note_id: int) -> BackgroundNote:
    note = db.get(BackgroundNote, note_id)
    if note is None or note.deleted_at is not None:
        raise ApiError(404, "Not found", "That note does not exist.")
    return note


def _clean(title: str | None, body: str | None) -> tuple[str | None, str | None]:
    if title is not None:
        title = " ".join(title.split())
        if not title:
            raise ApiError(422, "Invalid note", "Give the note a title.")
    if body is not None:
        body = body.strip()
        if not body:
            raise ApiError(422, "Invalid note", "Write something in the note.")
        if len(body) > NOTE_LIMIT:
            raise ApiError(
                422,
                "Note too long",
                f"A note can have {NOTE_LIMIT} characters; this one has {len(body)}. "
                "Shorten it, or split it into two notes.",
            )
    return title, body


@router.get("/notes", response_model=NotesOut)
def list_notes(_user: UserDep, db: DbDep) -> NotesOut:
    rows = list(
        db.scalars(
            select(BackgroundNote)
            .where(BackgroundNote.deleted_at.is_(None))
            .order_by(BackgroundNote.updated_at.desc(), BackgroundNote.id.desc())
        )
    )
    handed = helper_notes(db)
    return NotesOut(
        notes=[_out(n) for n in rows],
        note_limit=NOTE_LIMIT,
        total_limit=TOTAL_LIMIT,
        used=handed.used,
        left_out=handed.left_out,
    )


@router.post("/notes", response_model=NoteOut, status_code=201)
def create_note(body: NoteIn, _user: UserDep, db: DbDep) -> NoteOut:
    if body.source not in SOURCES:  # the Literal already guards this; kept for the constant
        raise ApiError(422, "Invalid note", "Unknown source.")
    title, text = _clean(body.title, body.body)
    note = BackgroundNote(
        title=title or "",
        body=text or "",
        source=body.source,
        use_in_helper=body.use_in_helper,
    )
    db.add(note)
    db.flush()
    write_audit(db, "user", "background_note", "create", entity_id=note.id)
    return _out(note)


@router.patch("/notes/{note_id}", response_model=NoteOut)
def change_note(note_id: int, body: NoteChanges, _user: UserDep, db: DbDep) -> NoteOut:
    note = _load(db, note_id)
    title, text = _clean(body.title, body.body)
    if title is not None:
        note.title = title
    if text is not None:
        note.body = text
    if body.use_in_helper is not None:
        note.use_in_helper = body.use_in_helper
    db.flush()
    write_audit(
        db,
        "user",
        "background_note",
        "update",
        entity_id=note.id,
        diff={k: v for k, v in body.model_dump(exclude_none=True).items() if k != "body"},
    )
    return _out(note)


@router.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: int, _user: UserDep, db: DbDep) -> None:
    note = _load(db, note_id)
    note.deleted_at = dt.datetime.now(dt.UTC)
    write_audit(db, "user", "background_note", "delete", entity_id=note.id)


@router.get("/notes/request", response_model=PromptOut)
def background_request(_user: UserDep) -> PromptOut:
    """The text to paste into a chat with Claude, to get a profile back that can be saved as a
    note (the free way, on the Claude subscription)."""
    return PromptOut(text=load_prompt("background_request").text)
