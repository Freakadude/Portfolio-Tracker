from pathlib import Path

import pytest

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import Secret
from folio.security.secrets import SecretDecryptError, SecretStore, mask
from tests.conftest import TEST_SECRET

SENTINEL = "sk-ant-SENTINEL-plaintext-key-0123456789"


def _factory(settings: Settings):  # type: ignore[no-untyped-def]
    return make_session_factory(make_engine(settings.db_url))


def test_round_trip_and_update(settings: Settings) -> None:
    with _factory(settings)() as db:
        store = SecretStore(db, TEST_SECRET)
        assert store.get("anthropic") is None
        store.set("anthropic", SENTINEL)
        db.commit()
        assert store.get("anthropic") == SENTINEL
        store.set("anthropic", "replacement-value-1234")
        db.commit()
        assert store.get("anthropic") == "replacement-value-1234"
        assert store.names() == ["anthropic"]
        store.delete("anthropic")
        db.commit()
        assert not store.has("anthropic")


def test_masked_shows_at_most_last_four(settings: Settings) -> None:
    with _factory(settings)() as db:
        store = SecretStore(db, TEST_SECRET)
        store.set("anthropic", SENTINEL)
        store.set("short", "abc123")
        db.commit()
        masked = store.masked("anthropic")
        assert masked is not None and masked.endswith(SENTINEL[-4:])
        assert SENTINEL[:-4] not in masked
        assert store.masked("short") == mask("abc123") == "•" * 8  # too short to reveal any


def test_database_files_contain_no_plaintext(settings: Settings) -> None:
    factory = _factory(settings)
    with factory() as db:
        SecretStore(db, TEST_SECRET).set("anthropic", SENTINEL)
        db.commit()
    db_path = Path(settings.db_url.removeprefix("sqlite:///"))
    blobs = [p.read_bytes() for p in db_path.parent.glob(f"{db_path.name}*")]
    assert blobs and not any(SENTINEL.encode() in b for b in blobs)


def test_wrong_secret_key_cannot_decrypt(settings: Settings) -> None:
    with _factory(settings)() as db:
        SecretStore(db, TEST_SECRET).set("anthropic", SENTINEL)
        db.commit()
        with pytest.raises(SecretDecryptError):
            SecretStore(db, "another-secret-key-0123456789abcdef0123456789").get("anthropic")


def test_repr_never_shows_ciphertext(settings: Settings) -> None:
    with _factory(settings)() as db:
        store = SecretStore(db, TEST_SECRET)
        store.set("anthropic", SENTINEL)
        db.commit()
        row = db.query(Secret).one()
        assert row.ciphertext not in repr(row)
