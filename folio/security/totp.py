"""Time-based one-time passwords (FR-SY-03, RFC 6238) on the standard library, and the recovery
codes that stand in for them.

HMAC-SHA1, 30 second steps, six digits: what every authenticator app (Aegis, 2FAS, Google
Authenticator, 1Password) expects. A code is accepted for its own step and one step either side
(clock drift), and never twice: the step of the last accepted code is remembered, and a code from
that step or an earlier one is refused. The QR code is drawn by `segno` as SVG.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from datetime import datetime
from urllib.parse import quote

import segno

STEP_SECONDS = 30
DIGITS = 6
WINDOW = 1  # steps either side of now that are still accepted
SECRET_BYTES = 20  # 160 bits, the size RFC 4226 recommends
ISSUER = "Folio"
RECOVERY_COUNT = 10
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0, O, 1, I: read aloud or copied by hand


def new_secret() -> str:
    """A fresh shared secret, base32 without padding, as authenticator apps take it."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    cleaned = secret.replace(" ", "").upper()
    return base64.b32decode(cleaned + "=" * (-len(cleaned) % 8))


def hotp(secret: str, counter: int) -> str:
    """RFC 4226: the code for one counter value."""
    digest = hmac.new(_key(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def step_of(moment: datetime) -> int:
    return int(moment.timestamp()) // STEP_SECONDS


def code_at(secret: str, moment: datetime) -> str:
    return hotp(secret, step_of(moment))


def verify(secret: str, code: str, now: datetime, last_step: int | None = None) -> int | None:
    """The step the code belongs to when it is valid now and was not used before, else None.
    The caller stores the returned step as the last one used."""
    cleaned = code.replace(" ", "").replace("-", "")
    if len(cleaned) != DIGITS or not (cleaned.isascii() and cleaned.isdigit()):
        return None
    current = step_of(now)
    matched: int | None = None
    for step in range(current - WINDOW, current + WINDOW + 1):  # every step: constant work
        if hmac.compare_digest(hotp(secret, step), cleaned):
            matched = step
    if matched is None or (last_step is not None and matched <= last_step):
        return None
    return matched


def provisioning_uri(secret: str, account: str) -> str:
    """The otpauth link an authenticator app reads from the QR code."""
    label = quote(f"{ISSUER}:{account}", safe="")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}"
        f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"
    )


def qr_svg(uri: str) -> str:
    """The link as an SVG QR code, sized by the page (no fixed width or height)."""
    code = segno.make(uri, error="m")
    return str(code.svg_inline(scale=1, border=2, dark="#000", light="#fff", omitsize=True))


def group(secret: str) -> str:
    """The secret in groups of four, easier to type: ABCD EFGH ..."""
    return " ".join(secret[i : i + 4] for i in range(0, len(secret), 4))


def new_recovery_codes(count: int = RECOVERY_COUNT) -> list[str]:
    """One-time codes like K7QM-2XPD-9HVT, each worth one login. Shown once, stored hashed."""
    return [
        "-".join("".join(secrets.choice(_ALPHABET) for _ in range(4)) for _ in range(3))
        for _ in range(count)
    ]


def normalize_recovery(code: str) -> str:
    return code.replace(" ", "").replace("-", "").upper()
