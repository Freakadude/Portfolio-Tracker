"""Shared helpers for provider tests: recorded fixtures and a scripted HTTP transport."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
from tenacity import wait_none

from folio.marketdata.http import HttpClient

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "providers"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class Scripted:
    """An httpx transport that answers from a handler and remembers every request."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._handler = handler
        self.transport = httpx.MockTransport(self._answer)

    def _answer(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)


def respond(name: str, status: int = 200, content_type: str = "application/json") -> httpx.Response:
    return httpx.Response(
        status, content=fixture_bytes(name), headers={"content-type": content_type}
    )


def client(provider: str, scripted: Scripted, **kwargs: object) -> HttpClient:
    """No real waiting between retries in tests."""
    kwargs.setdefault("wait", wait_none())
    return HttpClient(provider, transport=scripted.transport, **kwargs)  # type: ignore[arg-type]
