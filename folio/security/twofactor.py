"""The owner's second factor (FR-SY-03): set up, enable, check at login, disable.

The shared secret is kept encrypted with a key derived from FOLIO_SECRET_KEY (its own purpose,
apart from the stored API keys). A secret that was set up but never confirmed does nothing: only
after a valid code is entered does the login start to ask for one, so a half-finished setup can
never lock the owner out.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from folio.db.models import RecoveryCode, User
from folio.security import totp
from folio.security.keys import derive_key
from folio.security.passwords import hash_password, verify_password
from folio.security.redact import register


class TwoFactorError(ValueError):
    """The request cannot be done; the message is for the owner."""


@dataclass(frozen=True)
class Status:
    enabled: bool
    pending: bool  # a secret was set up but not confirmed yet
    recovery_codes_left: int


def _fernet(secret_key: str) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(derive_key(secret_key, "totp")))


def _secret(user: User, secret_key: str) -> str | None:
    if not user.totp_secret_enc:
        return None
    try:
        value = _fernet(secret_key).decrypt(user.totp_secret_enc.encode()).decode()
    except InvalidToken as exc:
        raise TwoFactorError(
            "The stored second factor cannot be read, usually because FOLIO_SECRET_KEY changed."
        ) from exc
    register(value)
    return value


def status(db: Session, user: User) -> Status:
    left = len(
        db.scalars(
            select(RecoveryCode.id).where(
                RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None)
            )
        ).all()
    )
    return Status(
        enabled=user.totp_enabled,
        pending=bool(user.totp_secret_enc) and not user.totp_enabled,
        recovery_codes_left=left if user.totp_enabled else 0,
    )


def start_setup(db: Session, user: User, secret_key: str) -> tuple[str, str]:
    """A new secret and the link for the authenticator app. It is kept, unconfirmed, until
    `enable` is called with a code from the app. Refused while the second factor is on."""
    if user.totp_enabled:
        raise TwoFactorError(
            "Two-factor sign-in is already on. Turn it off first to set it up again."
        )
    secret = totp.new_secret()
    register(secret)
    user.totp_secret_enc = _fernet(secret_key).encrypt(secret.encode()).decode()
    user.totp_last_step = None
    return secret, totp.provisioning_uri(secret, user.username)


def _store_codes(db: Session, user: User) -> list[str]:
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    codes = totp.new_recovery_codes()
    for code in codes:
        db.add(
            RecoveryCode(user_id=user.id, code_hash=hash_password(totp.normalize_recovery(code)))
        )
    db.flush()
    return codes


def enable(db: Session, user: User, code: str, now: datetime, secret_key: str) -> list[str]:
    """Confirm the setup with a code from the app, turn the second factor on and return the
    recovery codes (shown once)."""
    if user.totp_enabled:
        raise TwoFactorError("Two-factor sign-in is already on.")
    secret = _secret(user, secret_key)
    if secret is None:
        raise TwoFactorError("Start the setup first.")
    step = totp.verify(secret, code, now, user.totp_last_step)
    if step is None:
        raise TwoFactorError("That code is not right. Check the clock of your phone and try again.")
    user.totp_enabled, user.totp_last_step = True, step
    return _store_codes(db, user)


def check_login(db: Session, user: User, code: str, now: datetime, secret_key: str) -> bool:
    """A code (or an unused recovery code) at sign-in. A code works once; a recovery code is
    used up."""
    secret = _secret(user, secret_key)
    if secret is not None:
        step = totp.verify(secret, code, now, user.totp_last_step)
        if step is not None:
            user.totp_last_step = step
            return True
    wanted = totp.normalize_recovery(code)
    if len(wanted) != 12:  # not the shape of a recovery code: no hashing for nothing
        return False
    for row in db.scalars(
        select(RecoveryCode).where(RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None))
    ):
        if verify_password(row.code_hash, wanted):
            row.used_at = now
            return True
    return False


def disable(db: Session, user: User, password: str, code: str, now: datetime, key: str) -> None:
    """Turn it off. Needs the password and a code (or recovery code), so a stolen session alone
    cannot remove the second factor."""
    if not user.totp_enabled:
        raise TwoFactorError("Two-factor sign-in is not on.")
    if not verify_password(user.password_hash, password):
        raise TwoFactorError("The password is not right.")
    if not check_login(db, user, code, now, key):
        raise TwoFactorError("That code is not right.")
    user.totp_enabled, user.totp_secret_enc, user.totp_last_step = False, None, None
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))


def new_codes(
    db: Session, user: User, password: str, code: str, now: datetime, key: str
) -> list[str]:
    """Replace the recovery codes (the old ones stop working); same checks as turning it off."""
    if not user.totp_enabled:
        raise TwoFactorError("Two-factor sign-in is not on.")
    if not verify_password(user.password_hash, password):
        raise TwoFactorError("The password is not right.")
    if not check_login(db, user, code, now, key):
        raise TwoFactorError("That code is not right.")
    return _store_codes(db, user)
