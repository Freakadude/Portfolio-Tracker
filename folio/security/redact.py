"""Keeps secrets out of logs (FR-SY-05). Known secret values are registered when they are
stored or read; common key shapes are caught even when unregistered."""

import re
import threading

_lock = threading.Lock()
_known: set[str] = set()

_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{12,}"),
]
REDACTED = "[REDACTED]"
_MIN_LENGTH = 6  # shorter values would redact ordinary words


def register(value: str) -> None:
    if len(value) >= _MIN_LENGTH:
        with _lock:
            _known.add(value)


def scrub(text: str) -> str:
    with _lock:
        known = sorted(_known, key=len, reverse=True)
    for value in known:
        text = text.replace(value, REDACTED)
    for pattern in _PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def scrub_value(value: object) -> object:
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, dict):
        return {k: scrub_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [scrub_value(v) for v in value]
    return value
