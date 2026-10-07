"""The strategy helper: the owner's background notes (ADR 0048).

The notes are what the helper is told about the owner. They are kept locally, are included in the
backups, and are given to nothing but the strategy helper.
"""

import datetime as dt
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.agent import budget, chat_summary, strategist
from folio.agent.background import NOTE_LIMIT, SOURCES, TOTAL_LIMIT, helper_notes
from folio.agent.chat_export import MAX_UPLOAD, Chat, ExportError, read_export
from folio.agent.prompt_files import load_prompt
from folio.agent.runtime import make_llm
from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.api.routers.strategies import DiffRowOut
from folio.audit import write_audit
from folio.db.base import utcnow
from folio.db.models_insight import BackgroundNote
from folio.strategies import service as strategy_service
from folio.strategies.diff import side_by_side

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


# --- chats exported from claude.ai ---------------------------------------------------------


class ChatInfoOut(BaseModel):
    id: str
    title: str
    created_at: str | None
    messages: int
    characters: int
    hits: int  # messages that mention investing
    relevant: bool
    opening: str


class ChatScanOut(BaseModel):
    chats: list[ChatInfoOut]
    total: int
    relevant: int


class ChatEstimateOut(BaseModel):
    chats: int
    tokens: int
    cost_eur: Decimal  # the most it can cost
    remaining_eur: Decimal
    fits: bool
    model: str
    max_chats: int


class ChatSummaryOut(BaseModel):
    id: str
    title: str
    text: str | None  # None: nothing about the owner's own investing in that chat
    cost_eur: Decimal


class ChatFailureOut(BaseModel):
    id: str
    title: str
    reason: str


class ChatSummariesOut(BaseModel):
    summaries: list[ChatSummaryOut]
    failed: list[ChatFailureOut]
    stopped: str | None  # why the work stopped before the last chat (the budget)
    cost_eur: Decimal


SCAN_SHOWN = 200


async def _chats(file: UploadFile) -> list[Chat]:
    data = await file.read(MAX_UPLOAD + 1)
    try:
        return read_export(data)
    except ExportError as exc:
        raise ApiError(422, "Not an export of chats", str(exc)) from exc


def _chosen(chats: list[Chat], ids: str) -> list[Chat]:
    wanted = [i for i in (p.strip() for p in ids.split(",")) if i]
    if not wanted:
        raise ApiError(422, "Nothing chosen", "Tick the chats you want summarised.")
    if len(wanted) > chat_summary.MAX_CHATS:
        raise ApiError(
            422,
            "Too many chats at once",
            f"Summarise up to {chat_summary.MAX_CHATS} chats at a time; do the rest afterwards.",
        )
    by_id = {c.id: c for c in chats}
    missing = [i for i in wanted if i not in by_id]
    if missing:
        raise ApiError(422, "Chat not found", "A chosen chat is not in that file.")
    return [by_id[i] for i in wanted]


@router.post("/chats/scan", response_model=ChatScanOut)
async def scan_chats(_user: UserDep, file: Annotated[UploadFile, File()]) -> ChatScanOut:
    """The chats in a claude.ai export, those about investing first. Nothing is stored."""
    chats = await _chats(file)
    return ChatScanOut(
        chats=[
            ChatInfoOut(
                id=c.id,
                title=c.title,
                created_at=c.created_at,
                messages=c.messages,
                characters=c.characters,
                hits=c.hits,
                relevant=c.relevant,
                opening=c.opening,
            )
            for c in chats[:SCAN_SHOWN]
        ],
        total=len(chats),
        relevant=sum(c.relevant for c in chats),
    )


@router.post("/chats/estimate", response_model=ChatEstimateOut)
async def estimate_chats(
    _user: UserDep,
    db: DbDep,
    file: Annotated[UploadFile, File()],
    ids: Annotated[str, Form()],
) -> ChatEstimateOut:
    """What summarising the chosen chats can cost at most, before anything is sent."""
    chosen = _chosen(await _chats(file), ids)
    cfg = budget.agent_settings(db)
    try:
        est = chat_summary.estimate(db, cfg, budget.timezone_of(db), utcnow(), chosen)
    except budget.BudgetExceeded as exc:
        raise ApiError(409, "No price", str(exc)) from exc
    return ChatEstimateOut(
        chats=est.chats,
        tokens=est.tokens,
        cost_eur=est.cost_eur,
        remaining_eur=est.remaining_eur,
        fits=est.fits,
        model=est.model,
        max_chats=chat_summary.MAX_CHATS,
    )


@router.post("/chats/summarise", response_model=ChatSummariesOut)
async def summarise_chats(
    request: Request,
    _user: UserDep,
    db: DbDep,
    file: Annotated[UploadFile, File()],
    ids: Annotated[str, Form()],
) -> ChatSummariesOut:
    """Summarise the chosen chats about the owner's own investing, one cheap call per chat within
    the monthly budget. The summaries are returned to be read and edited; they are not saved."""
    chosen = _chosen(await _chats(file), ids)
    cfg = budget.agent_settings(db)
    state = request.app.state
    llm = make_llm(db, state.settings, getattr(state, "llm_transport", None))
    if llm is None:
        raise ApiError(
            409,
            "The AI agent is off",
            "Turn the agent on and save your Anthropic API key in Settings, Agent first. "
            "Or use the free way: ask Claude to write the profile itself.",
        )
    done, failed, stopped = chat_summary.summarise(
        db, llm, cfg, budget.timezone_of(db), utcnow(), chosen
    )
    return ChatSummariesOut(
        summaries=[
            ChatSummaryOut(id=d.id, title=d.title, text=d.text, cost_eur=d.cost_eur) for d in done
        ],
        failed=[ChatFailureOut(id=f.id, title=f.title, reason=f.reason) for f in failed],
        stopped=stopped,
        cost_eur=sum((d.cost_eur for d in done), Decimal(0)),
    )


# --- the free mode: a prompt for claude.ai, and checking what comes back ---------------


class HelperPromptOut(BaseModel):
    text: str
    characters: int
    notes_used: int  # characters of your background notes that are in it


class ProposalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_id: int
    yaml: str = Field(min_length=1)


class ProposalDiffOut(BaseModel):
    rows: list[DiffRowOut]
    changed: bool


@router.get("/prompt", response_model=HelperPromptOut)
def helper_prompt(
    _user: UserDep,
    db: DbDep,
    mode: Literal["new", "revise"] = "new",
    strategy: int | None = None,
) -> HelperPromptOut:
    """One prompt to paste into a chat with Claude on the subscription: the rules of the
    interview, the format of a strategy, the holdings as shares (no euro amounts), the background
    notes and, to revise, the current strategy. Claude answers with a strategy that is pasted back
    and checked like any other."""
    if mode == "revise" and strategy is None:
        raise ApiError(422, "Which strategy?", "Choose the strategy to revise.")
    today = dt.date.today()
    try:
        text = strategist.paste_prompt(db, today, strategy if mode == "revise" else None)
    except strategy_service.StrategyNotFound:
        raise ApiError(404, "Not found", "That strategy does not exist.") from None
    return HelperPromptOut(text=text, characters=len(text), notes_used=helper_notes(db).used)


@router.post("/diff", response_model=ProposalDiffOut)
def proposal_diff(body: ProposalIn, _user: UserDep, db: DbDep) -> ProposalDiffOut:
    """What a proposed strategy changes against the strategy it would revise, line by line."""
    try:
        current = strategy_service.latest(db, strategy_service.load(db, body.strategy_id))
    except strategy_service.StrategyNotFound:
        raise ApiError(404, "Not found", "That strategy does not exist.") from None
    rows = side_by_side(current.yaml, body.yaml)
    return ProposalDiffOut(
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
        changed=any(r.kind != "same" for r in rows),
    )
