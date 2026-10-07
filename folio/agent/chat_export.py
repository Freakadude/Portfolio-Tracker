"""Reading an export of the owner's chats with Claude (ADR 0048).

claude.ai lets the owner export their data (Settings, Privacy, Export data): a zip with a
`conversations.json`. This module reads it in memory, finds the conversations that look like
talks about investing, and cuts a conversation down to a transcript of bounded size. The export
file itself is never stored. Whatever the chats say is data: it is only ever summarised, and the
summary is shown to the owner before it becomes a note.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass
from typing import Any

MAX_UPLOAD = 200 * 1024 * 1024  # bytes of the file the owner sends
MAX_JSON = 600 * 1024 * 1024  # bytes of conversations.json once unpacked
TRANSCRIPT_LIMIT = 40_000  # characters of one chat that are summarised
RELEVANT_HITS = 2  # messages that mention investing, for a chat to count as one about investing
OPENING = 200

KEYWORDS = re.compile(
    r"invest|portfolio|\betfs?\b|\bstocks?\b|\bshares?\b|\bbonds?\b|equit|dividend|allocation|"
    r"rebalanc|retire|pension|index fund|crypto|bitcoin|\bgold\b|inflation|broker|degiro|"
    r"drawdown|risk toleranc|msci|s&p|nasdaq|\byield\b|savings rate|asset class",
    re.IGNORECASE,
)


class ExportError(ValueError):
    """The file is not a claude.ai export; the message is for the owner."""


@dataclass(frozen=True)
class Chat:
    id: str
    title: str
    created_at: str | None
    messages: int
    characters: int
    hits: int  # messages that mention investing
    opening: str
    turns: tuple[tuple[str, str], ...]  # (who, text)

    @property
    def relevant(self) -> bool:
        return self.hits >= RELEVANT_HITS


def _message_text(message: dict[str, Any]) -> str:
    text = message.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    parts = message.get("content")
    if isinstance(parts, list):
        found = [
            str(p.get("text", "")).strip()
            for p in parts
            if isinstance(p, dict) and p.get("type") == "text"
        ]
        return "\n".join(f for f in found if f)
    return ""


def _chat(raw: dict[str, Any]) -> Chat | None:
    ident = raw.get("uuid") or raw.get("id")
    messages = raw.get("chat_messages")
    if not isinstance(ident, str) or not isinstance(messages, list):
        return None
    turns: list[tuple[str, str]] = []
    hits = 0
    for m in messages:
        if not isinstance(m, dict):
            continue
        text = _message_text(m)
        if not text:
            continue
        who = "Me" if m.get("sender") == "human" else "Claude"
        turns.append((who, text))
        hits += bool(KEYWORDS.search(text))
    if not turns:
        return None
    first_mine = next((t for w, t in turns if w == "Me"), turns[0][1])
    created = raw.get("created_at")
    return Chat(
        id=ident,
        title=" ".join(str(raw.get("name") or "").split())[:120] or "Untitled chat",
        created_at=created if isinstance(created, str) else None,
        messages=len(turns),
        characters=sum(len(t) for _, t in turns),
        hits=hits,
        opening=" ".join(first_mine.split())[:OPENING],
        turns=tuple(turns),
    )


def _unpack(data: bytes) -> bytes:
    if data[:2] != b"PK":
        return data  # the json itself
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith("conversations.json")]
            if not names:
                raise ExportError(
                    "This zip has no conversations.json. Use the file you get from claude.ai: "
                    "Settings, Privacy, Export data."
                )
            with archive.open(names[0]) as member:
                raw = member.read(MAX_JSON + 1)
    except zipfile.BadZipFile as exc:
        raise ExportError("That file is not a zip file that can be read.") from exc
    if len(raw) > MAX_JSON:
        raise ExportError("conversations.json is larger than Folio reads.")
    return raw


def read_export(data: bytes) -> list[Chat]:
    """Every chat in the export that has text, best matches for investing first, then newest."""
    if len(data) > MAX_UPLOAD:
        raise ExportError("That file is larger than Folio reads.")
    try:
        loaded = json.loads(_unpack(data))
    except ExportError:
        raise
    except (ValueError, UnicodeDecodeError) as exc:
        raise ExportError(
            "That file could not be read as an export of chats. Use the zip (or the "
            "conversations.json in it) from claude.ai: Settings, Privacy, Export data."
        ) from exc
    if not isinstance(loaded, list):
        raise ExportError("This does not look like conversations.json: a list of chats is missing.")
    chats = [c for c in (_chat(r) for r in loaded if isinstance(r, dict)) if c is not None]
    return sorted(chats, key=lambda c: (c.hits, c.created_at or ""), reverse=True)


def transcript(chat: Chat) -> str:
    """The chat as text, cut in the middle when it is longer than the limit."""
    text = "\n\n".join(f"{who}: {t}" for who, t in chat.turns)
    if len(text) <= TRANSCRIPT_LIMIT:
        return text
    half = TRANSCRIPT_LIMIT // 2
    return f"{text[:half]}\n\n[... the middle of the chat is left out ...]\n\n{text[-half:]}"
