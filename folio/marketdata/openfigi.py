"""OpenFIGI: ISIN to listings (symbol resolution, FR-INS-01). Free; 25 requests per minute
without a key. Built against responses recorded from the live API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from folio.marketdata.base import ProviderError
from folio.marketdata.http import HttpClient, check_status

URL = "https://api.openfigi.com/v3/mapping"


@dataclass(frozen=True)
class FigiListing:
    figi: str
    name: str
    ticker: str
    exch_code: str  # Bloomberg exchange code, e.g. NA for Euronext Amsterdam
    security_type: str | None
    security_type2: str | None
    market_sector: str | None


class FigiMapper:
    name = "openfigi"

    def __init__(self, http: HttpClient, api_key: str | None = None) -> None:
        self._http = http
        self._key = api_key

    def map_isin(self, isin: str) -> list[FigiListing]:
        headers = {"X-OPENFIGI-APIKEY": self._key} if self._key else None
        response = self._http.request(
            "POST",
            URL,
            json=[{"idType": "ID_ISIN", "idValue": isin}],
            headers=headers,
        )
        check_status(self.name, response)
        try:
            first: dict[str, Any] = response.json()[0]
        except (ValueError, IndexError, KeyError) as exc:
            raise ProviderError("OpenFIGI sent a response that could not be read.") from exc
        if "error" in first:
            raise ProviderError(f"OpenFIGI could not look up {isin}: {first['error']}")
        if "warning" in first:  # e.g. "No identifier found."
            return []
        return [
            FigiListing(
                figi=row["figi"],
                name=row.get("name", ""),
                ticker=row.get("ticker", ""),
                exch_code=row.get("exchCode", ""),
                security_type=row.get("securityType"),
                security_type2=row.get("securityType2"),
                market_sector=row.get("marketSector"),
            )
            for row in first.get("data", [])
        ]
