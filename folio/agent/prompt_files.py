"""Versioned prompt files (FR-AG-10).

Prompts are plain text files in `folio/agent/prompts/`, each starting with a header:

    ---
    version: 3
    ---

A run records the label of every prompt it used, `name@version+digest`, where the digest is the
first eight characters of a hash of the text. Editing a prompt therefore changes the recorded
label even if nobody remembers to bump the version, and the run trace shows exactly which wording
produced a recommendation.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
_HEADER = re.compile(r"\A---\s*\nversion:\s*(\d+)\s*\n---\s*\n", re.ASCII)


class PromptError(ValueError):
    """A prompt file is missing or has no version header."""


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    text: str
    digest: str

    @property
    def label(self) -> str:
        return f"{self.name}@{self.version}+{self.digest}"


def load_prompt(name: str, directory: Path = PROMPT_DIR) -> Prompt:
    path = directory / f"{name}.md"
    if not path.is_file():
        raise PromptError(f"The prompt file {path.name} does not exist.")
    raw = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    header = _HEADER.match(raw)
    if header is None:
        raise PromptError(f"{path.name} must start with a header giving its version.")
    text = raw[header.end() :].strip()
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return Prompt(name, int(header.group(1)), text, digest)


def labels(prompts: list[Prompt]) -> str:
    """What a run records: every prompt it used, in the order given."""
    return ", ".join(p.label for p in prompts)
