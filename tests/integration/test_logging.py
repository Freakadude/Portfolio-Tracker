import io
import json
import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.logging import configure_logging, get_logger
from folio.security.secrets import SecretStore
from tests.conftest import TEST_SECRET

SENTINEL = "sk-ant-SENTINEL-logged-key-0123456789"


@pytest.fixture
def log_stream() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    yield stream
    logging.getLogger().handlers.clear()


def _lines(stream: io.StringIO) -> list[dict]:  # type: ignore[type-arg]
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


def test_access_log_is_json_with_request_id(client: TestClient, log_stream: io.StringIO) -> None:
    r = client.get("/healthz")
    access = [ln for ln in _lines(log_stream) if ln.get("path") == "/healthz"]
    assert len(access) == 1
    entry = access[0]
    assert entry["status"] == 200 and entry["method"] == "GET"
    assert entry["request_id"] == r.headers["x-request-id"]
    assert entry["level"] == "info" and "timestamp" in entry


def test_each_request_gets_its_own_id(client: TestClient, log_stream: io.StringIO) -> None:
    a = client.get("/healthz").headers["x-request-id"]
    b = client.get("/healthz").headers["x-request-id"]
    assert a != b


def test_known_secrets_are_scrubbed_from_logs(settings: Settings, log_stream: io.StringIO) -> None:
    with make_session_factory(make_engine(settings.db_url))() as db:
        SecretStore(db, TEST_SECRET).set("anthropic", "my-very-private-token-9876")
        db.commit()
    log = get_logger("test")
    log.info("calling provider with my-very-private-token-9876")
    log.info("header", authorization="Bearer abcdefghijklmnop12345", key=SENTINEL)
    logging.getLogger("third.party").warning("stdlib logger leaks %s", SENTINEL)
    text = log_stream.getvalue()
    assert "my-very-private-token-9876" not in text
    assert "abcdefghijklmnop12345" not in text
    assert SENTINEL not in text
    assert "[REDACTED]" in text
