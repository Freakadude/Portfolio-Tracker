import base64

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.db.models import Secret
from folio.security.keys import derive_key


class SecretDecryptError(Exception):
    """The stored secret cannot be decrypted, usually because FOLIO_SECRET_KEY changed."""


MASK_PREFIX = "\u2022"


def mask(value: str) -> str:
    """Display form for a saved secret: never more than the last 4 characters."""
    return "•" * 8 + value[-4:] if len(value) >= 12 else "•" * 8


class SecretStore:
    """Provider keys and tokens, encrypted at rest with a key derived from FOLIO_SECRET_KEY."""

    def __init__(self, db: Session, secret_key: str) -> None:
        self._db = db
        self._fernet = Fernet(base64.urlsafe_b64encode(derive_key(secret_key, "secrets")))

    def _row(self, name: str) -> Secret | None:
        return self._db.scalar(select(Secret).where(Secret.name == name))

    def set(self, name: str, value: str) -> None:
        ciphertext = self._fernet.encrypt(value.encode()).decode()
        row = self._row(name)
        if row is None:
            self._db.add(Secret(name=name, ciphertext=ciphertext))
        else:
            row.ciphertext = ciphertext

    def get(self, name: str) -> str | None:
        row = self._row(name)
        if row is None:
            return None
        try:
            return self._fernet.decrypt(row.ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise SecretDecryptError(f"cannot decrypt secret {name!r}") from exc

    def masked(self, name: str) -> str | None:
        value = self.get(name)
        return None if value is None else mask(value)

    def has(self, name: str) -> bool:
        return self._row(name) is not None

    def delete(self, name: str) -> None:
        row = self._row(name)
        if row is not None:
            self._db.delete(row)

    def names(self) -> list[str]:
        return list(self._db.scalars(select(Secret.name).order_by(Secret.name)))
