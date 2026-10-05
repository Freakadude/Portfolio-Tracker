"""Helpers for agent and LLM tests: a scripted stand-in for the Anthropic API.

The official SDK is used for real (it builds the requests and parses the answers); only the
network is replaced, by an `httpx2` mock transport that records every request body and answers
from a queue. The response shapes follow the Messages API documentation and were not recorded
from the live API (tests/fixtures/providers/README.md).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx2

from folio.agent.llm import LlmClient

KEY = "sk-ant-test-key-0123456789"  # gitleaks:allow


def message(
    *blocks: dict[str, Any],
    stop: str = "end_turn",
    model: str = "claude-sonnet-5-5",
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_read: int = 0,
    cache_write: int = 0,
    searches: int = 0,
) -> dict[str, Any]:
    usage: dict[str, Any] = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_creation_input_tokens": cache_write,
        "cache_read_input_tokens": cache_read,
    }
    if searches:
        usage["server_tool_use"] = {"web_search_requests": searches, "web_fetch_requests": 0}
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": list(blocks),
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": usage,
    }


def text(value: str) -> dict[str, Any]:
    return {"type": "text", "text": value}


def tool_use(name: str, tool_id: str = "toolu_1", **arguments: Any) -> dict[str, Any]:
    return {"type": "tool_use", "id": tool_id, "name": name, "input": arguments}


def error(status: int, kind: str, message_text: str) -> httpx2.Response:
    return httpx2.Response(
        status, json={"type": "error", "error": {"type": kind, "message": message_text}}
    )


class ScriptedLlm:
    """Answers each request from a queue (or a function), and remembers the request bodies."""

    def __init__(
        self,
        *answers: dict[str, Any] | httpx2.Response,
        handler: Callable[[dict[str, Any]], dict[str, Any] | httpx2.Response] | None = None,
    ) -> None:
        self.requests: list[dict[str, Any]] = []
        self.headers: list[httpx2.Headers] = []
        self._queue = list(answers)
        self._handler = handler
        self.transport = httpx2.MockTransport(self._answer)

    def _answer(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        self.headers.append(request.headers)
        if self._handler is not None:
            given = self._handler(body)
        elif self._queue:
            given = self._queue.pop(0)
        else:
            return error(500, "api_error", "the script ran out of answers")
        return given if isinstance(given, httpx2.Response) else httpx2.Response(200, json=given)

    def client(self, max_retries: int = 0) -> LlmClient:
        return LlmClient(KEY, transport=self.transport, max_retries=max_retries)
