"""FRED, the St. Louis Fed's economic data API (FR-MD-08): daily macro series such as the US
10-year real yield (DFII10), the broad trade-weighted dollar (DTWEXBGS) and the Fed funds rate.
Free with an API key. Built from the API documentation; see tests/fixtures/providers/README.md.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from folio.marketdata.base import ProviderError
from folio.marketdata.http import HttpClient

URL = "https://api.stlouisfed.org/fred/series/observations"


class FredSeries:
    name = "fred"

    def __init__(self, http: HttpClient, key: str) -> None:
        self._http = http
        self._key = key

    def observations(
        self, series_id: str, start: date, end: date | None = None
    ) -> list[tuple[date, Decimal]]:
        """Dated values, oldest first. Days FRED marks as missing (".") are left out."""
        params = {
            "series_id": series_id,
            "api_key": self._key,
            "file_type": "json",
            "observation_start": start.isoformat(),
        }
        if end is not None:
            params["observation_end"] = end.isoformat()
        response = self._http.request("GET", URL, params=params)
        if response.status_code == 400:
            message = _error_message(response.json() if response.content else {})
            raise ProviderError(f"FRED refused the request for {series_id}: {message}")
        if response.status_code in (401, 403):
            raise ProviderError("FRED rejected the API key. Check it in Settings > Providers.")
        if response.status_code >= 400:
            raise ProviderError(f"FRED returned HTTP {response.status_code} for {series_id}.")
        return parse_observations(response.json())


def _error_message(body: object) -> str:
    if isinstance(body, dict) and body.get("error_message"):
        text = str(body["error_message"])
        # FRED's message about an unknown key repeats the key; keep it out of logs and the UI
        return "the API key is not valid" if "api_key" in text else text
    return "bad request"


def parse_observations(body: object) -> list[tuple[date, Decimal]]:
    if not isinstance(body, dict) or not isinstance(body.get("observations"), list):
        raise ProviderError("FRED sent a response that could not be read.")
    points = []
    for item in body["observations"]:
        raw = str(item.get("value", "")).strip()
        if raw in ("", "."):
            continue
        try:
            points.append((date.fromisoformat(item["date"]), Decimal(raw)))
        except (InvalidOperation, ValueError, KeyError) as exc:
            raise ProviderError("FRED sent a value that could not be read.") from exc
    return sorted(points)
