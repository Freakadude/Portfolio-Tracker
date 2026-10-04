from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def derive_key(secret_key: str, purpose: str, length: int = 32) -> bytes:
    """Independent sub-keys from FOLIO_SECRET_KEY, one per purpose (secrets, csrf, ...)."""
    return HKDF(
        algorithm=hashes.SHA256(),
        length=length,
        salt=None,
        info=f"folio:{purpose}".encode(),
    ).derive(secret_key.encode())
