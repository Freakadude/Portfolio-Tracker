"""Phone channels behind one interface (FR-NT-02): the Home Assistant companion app (owner
decision Q5) and ntfy. The inbox needs no channel: every notification is stored first.

Each adapter sends one message and raises ChannelError with a readable reason when it fails;
retries and the delivery log are the dispatcher's job.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

TIMEOUT = httpx.Timeout(10.0)
NTFY_PRIORITY = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}


@dataclass(frozen=True)
class PushMessage:
    title: str
    body: str
    severity: str
    link: str | None = None  # absolute URL opened by a tap
    tag: str | None = None  # groups pushes on the same subject on the phone


class ChannelError(Exception):
    """The channel did not take the message; the text is shown in the delivery log."""


class Channel(Protocol):
    name: str

    def send(self, message: PushMessage) -> None: ...


def _client(transport: httpx.BaseTransport | None) -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, transport=transport, follow_redirects=False)


def _post(client: httpx.Client, name: str, url: str, **kwargs: object) -> httpx.Response:
    try:
        response = client.post(url, **kwargs)  # type: ignore[arg-type]
    except httpx.TransportError as exc:
        raise ChannelError(f"{name} could not be reached ({type(exc).__name__}).") from exc
    if response.status_code in (401, 403):
        raise ChannelError(f"{name} refused the token (HTTP {response.status_code}).")
    if response.status_code == 404:
        raise ChannelError(f"{name} did not find the target (HTTP 404). Check the address.")
    if response.status_code >= 400:
        raise ChannelError(f"{name} answered HTTP {response.status_code}.")
    return response


class HomeAssistantChannel:
    """Calls Home Assistant's notify service for the companion app over its REST API with a
    long-lived access token: POST {url}/api/services/notify/<service>."""

    name = "home_assistant"

    def __init__(
        self, url: str, service: str, token: str, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._url = url.rstrip("/")
        self._service = service.removeprefix("notify.")
        self._token = token
        self._transport = transport

    def send(self, message: PushMessage) -> None:
        data: dict[str, object] = {}
        if message.link:
            data["url"] = message.link  # iOS
            data["clickAction"] = message.link  # Android
        if message.tag:
            data["tag"] = message.tag
        if message.severity == "critical":
            data["push"] = {"interruption-level": "time-sensitive"}
            data["priority"] = "high"
            data["ttl"] = 0
        with _client(self._transport) as client:
            _post(
                client,
                "Home Assistant",
                f"{self._url}/api/services/notify/{self._service}",
                json={"title": message.title, "message": message.body, "data": data},
                headers={"Authorization": f"Bearer {self._token}"},
            )


class NtfyChannel:
    """Publishes to an ntfy topic as JSON (so titles with accents survive):
    POST {url} with {"topic", "title", "message", "priority", "click", "tags"}."""

    name = "ntfy"

    def __init__(
        self,
        url: str,
        topic: str,
        token: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._url = url.rstrip("/")
        self._topic = topic
        self._token = token
        self._transport = transport

    def send(self, message: PushMessage) -> None:
        body: dict[str, object] = {
            "topic": self._topic,
            "title": message.title,
            "message": message.body,
            "priority": NTFY_PRIORITY.get(message.severity, 3),
        }
        if message.link:
            body["click"] = message.link
        if message.tag:
            body["tags"] = [message.tag[:60]]
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        with _client(self._transport) as client:
            _post(client, "ntfy", self._url, json=body, headers=headers)


CHANNELS = ("home_assistant", "ntfy")
