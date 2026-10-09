"""Text that came from outside the app, made harmless for the model."""

from __future__ import annotations

import re

_TAGS = re.compile(r"[<>]")


def untrusted(text: str) -> str:
    """Outside text, made harmless and marked as data."""
    return f"<untrusted>{_TAGS.sub(' ', text).strip()}</untrusted>"
