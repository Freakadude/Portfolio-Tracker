"""One HTTP client per provider: timeouts, retries with backoff, call budget, circuit breaker.

Every attempt, including retries, is charged against the provider's daily budget before it is
sent, because that is what the provider counts.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from tenacity.wait import wait_base

from folio.marketdata.base import ProviderError, ProviderUnavailable
from folio.marketdata.budget import CircuitBreaker, UsageTracker

USER_AGENT = "Mozilla/5.0 (compatible; Folio personal portfolio tracker)"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class _Retryable(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class HttpClient:
    def __init__(
        self,
        provider: str,
        *,
        usage: UsageTracker | None = None,
        breaker: CircuitBreaker | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 20.0,
        attempts: int = 3,
        wait: wait_base | None = None,
        switched_off: bool = False,
    ) -> None:
        self.provider = provider
        self._switched_off = switched_off  # the owner turned this provider off (Settings)
        self._usage = usage
        self._breaker = breaker
        self._attempts = attempts
        self._wait = wait or wait_exponential(multiplier=0.5, max=8)
        self._client = httpx.Client(
            transport=transport,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        weight: int = 1,
    ) -> httpx.Response:
        """Send a request. Returns any non-retryable response (the adapter reads 404 and so
        on); raises ProviderError when the provider cannot be reached after all attempts."""
        if self._switched_off:
            raise ProviderError(
                f"{self.provider} is switched off in Settings, Providers. Switch it on to use it."
            )
        if self._breaker is not None and not self._breaker.allow():
            raise ProviderUnavailable(
                f"{self.provider} failed repeatedly and is paused for a few minutes."
            )

        def attempt() -> httpx.Response:
            if self._usage is not None:
                self._usage.charge(self.provider, weight)  # BudgetExhausted is not retried
            try:
                response = self._client.request(
                    method, url, params=params, json=json, headers=headers
                )
            except httpx.TransportError as exc:
                raise _Retryable(f"network error ({type(exc).__name__})") from exc
            if response.status_code in RETRYABLE_STATUS:
                raise _Retryable(f"HTTP {response.status_code}")
            return response

        retrying = Retrying(
            stop=stop_after_attempt(self._attempts),
            wait=self._wait,
            retry=retry_if_exception_type(_Retryable),
            reraise=True,
        )
        try:
            response: httpx.Response = retrying(attempt)
        except _Retryable as exc:
            if self._breaker is not None:
                self._breaker.record_failure()
            raise ProviderError(
                f"{self.provider} did not answer after {self._attempts} attempts ({exc.reason})."
            ) from exc
        if self._breaker is not None:
            self._breaker.record_success()
        return response


def check_status(provider: str, response: httpx.Response) -> None:
    """Common handling of non-success statuses an adapter does not treat specially."""
    if response.status_code in (401, 402, 403):
        raise ProviderError(
            f"{provider} rejected the request (HTTP {response.status_code}). "
            "Check the API key and plan in Settings > Providers."
        )
    if response.status_code >= 400:
        raise ProviderError(f"{provider} returned HTTP {response.status_code}.")


__all__ = ["HttpClient", "check_status"]
