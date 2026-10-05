"""The one place Folio talks to the Anthropic API (FR-AG-02, FR-AG-04).

A thin wrapper over the official SDK: it builds requests (prompt caching on the system prompt
and the tool definitions, optional server-side web search restricted to trusted domains,
optional structured output), reads the answer into plain data (text, tool calls, usage in
tokens and searches), and turns the SDK's errors into messages for the owner. Nothing here
logs or returns the API key. Tests give it an `httpx2` mock transport, so the real SDK builds
and parses real-shaped requests and responses without any network.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, cast

import anthropic
import httpx2

from folio.agent.cost import Usage

WEB_SEARCH_TOOL = "web_search_20250305"
DEFAULT_TIMEOUT = 120.0
CACHE = {"type": "ephemeral"}


class LlmError(Exception):
    """A call failed. `kind` is auth, billing, rate_limit, overloaded, network, refused or error;
    the message is written for the owner and never contains the API key."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class ToolUse:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class Reply:
    content: list[dict[str, Any]]  # the blocks as sent back by the API, to be returned verbatim
    text: str
    tool_uses: list[ToolUse]
    stop_reason: str  # end_turn | tool_use | max_tokens | pause_turn | refusal | stop_sequence
    usage: Usage
    model: str
    searches: list[dict[str, Any]] = field(default_factory=list)  # {"query", "urls"} per search


def system_blocks(*texts: str) -> list[dict[str, Any]]:
    """System prompt blocks; the last carries the cache breakpoint, so the stable prefix (the
    rules, then the strategy) is read from the cache on every later call of a run."""
    blocks: list[dict[str, Any]] = [{"type": "text", "text": t} for t in texts if t]
    if blocks:
        blocks[-1]["cache_control"] = CACHE
    return blocks


def web_search_tool(domains: Sequence[str], max_uses: int) -> dict[str, Any]:
    """Anthropic's server-side web search, limited to the owner's trusted domains."""
    tool: dict[str, Any] = {"type": WEB_SEARCH_TOOL, "name": "web_search", "max_uses": max_uses}
    if domains:
        tool["allowed_domains"] = list(domains)
    return tool


def with_cache(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The tool definitions with a cache breakpoint on the last one."""
    if not tools:
        return tools
    return [*tools[:-1], {**tools[-1], "cache_control": CACHE}]


def _usage(raw: Any) -> Usage:
    searches = 0
    if getattr(raw, "server_tool_use", None) is not None:
        searches = int(raw.server_tool_use.web_search_requests or 0)
    return Usage(
        input_tokens=int(raw.input_tokens or 0),
        output_tokens=int(raw.output_tokens or 0),
        cache_read_tokens=int(getattr(raw, "cache_read_input_tokens", 0) or 0),
        cache_write_tokens=int(getattr(raw, "cache_creation_input_tokens", 0) or 0),
        web_searches=searches,
    )


def _searches(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the model searched for and which pages came back, for the run trace."""
    out: list[dict[str, Any]] = []
    queries = {
        b["id"]: str(b.get("input", {}).get("query", ""))
        for b in blocks
        if b.get("type") == "server_tool_use" and b.get("name") == "web_search"
    }
    for b in blocks:
        if b.get("type") == "web_search_tool_result":
            content = b.get("content")
            urls = (
                [r.get("url") for r in content if isinstance(r, dict)]
                if isinstance(content, list)
                else []
            )
            out.append({"query": queries.get(b.get("tool_use_id", ""), ""), "urls": urls})
    return out


class LlmClient:
    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx2.BaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = 2,
    ) -> None:
        self._client = anthropic.Anthropic(
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries,
            http_client=httpx2.Client(transport=transport, timeout=timeout) if transport else None,
        )

    def create(
        self,
        *,
        model: str,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        max_tokens: int,
        tools: list[dict[str, Any]] | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> Reply:
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            params["tools"] = tools
        if output_schema is not None:
            params["output_config"] = {"format": {"type": "json_schema", "schema": output_schema}}
        try:
            message = self._client.messages.create(**params)
        except anthropic.AuthenticationError as exc:
            raise LlmError(
                "auth", "Anthropic refused the API key (HTTP 401). Check it in Settings, Agent."
            ) from exc
        except anthropic.PermissionDeniedError as exc:
            raise LlmError(
                "auth", "Anthropic says this key may not use that model (HTTP 403)."
            ) from exc
        except anthropic.RateLimitError as exc:
            raise LlmError(
                "rate_limit",
                "Anthropic is limiting requests right now (HTTP 429). Try again later.",
            ) from exc
        except (anthropic.APIConnectionError, anthropic.APITimeoutError) as exc:
            raise LlmError(
                "network", "Anthropic could not be reached; check the network and try again."
            ) from exc
        except anthropic.BadRequestError as exc:
            text = str(exc).lower()
            if "credit balance" in text or "billing" in text:
                raise LlmError(
                    "billing", "Anthropic says the account has no credit left (HTTP 400)."
                ) from exc
            raise LlmError("error", f"Anthropic rejected the request: {_brief(exc)}") from exc
        except anthropic.APIStatusError as exc:
            kind = "overloaded" if exc.status_code in (500, 502, 503, 529) else "error"
            raise LlmError(
                kind, f"Anthropic had a problem (HTTP {exc.status_code}); try again later."
            ) from exc
        blocks = [
            cast("dict[str, Any]", b.model_dump(mode="json", exclude_none=True))
            for b in message.content
        ]
        return Reply(
            content=blocks,
            text="".join(str(b.get("text", "")) for b in blocks if b.get("type") == "text"),
            tool_uses=[
                ToolUse(str(b["id"]), str(b["name"]), dict(b.get("input", {})))
                for b in blocks
                if b.get("type") == "tool_use"
            ],
            stop_reason=str(message.stop_reason or ""),
            usage=_usage(message.usage),
            model=str(message.model),
            searches=_searches(blocks),
        )


def _brief(exc: Exception) -> str:
    """The API's own words for what was wrong with a request."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        detail = body.get("error", body)
        if isinstance(detail, dict) and detail.get("message"):
            return str(detail["message"])[:300]
    return str(exc)[:300]
