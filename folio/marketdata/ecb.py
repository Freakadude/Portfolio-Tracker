"""ECB euro foreign exchange reference rates (FR-MD-06). Free, no key. Built against a response
recorded from the live SDMX API. Rates are published on TARGET working days only; callers use
the last earlier rate for other days."""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from folio.marketdata.base import ProviderError
from folio.marketdata.http import HttpClient, check_status

DATA = "https://data-api.ecb.europa.eu/service/data"
BASE = f"{DATA}/EXR"
DEPOSIT_RATE_KEY = "FM/D.U2.EUR.4F.KR.DFR.LEV"
DEPOSIT_RATE_URL = f"{DATA}/{DEPOSIT_RATE_KEY}"


@dataclass(frozen=True)
class FxObservation:
    date: date
    currency: str
    rate_per_eur: Decimal  # units of `currency` per 1 EUR


class EcbRates:
    name = "ecb"

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def fetch(
        self, currencies: Sequence[str], start: date, end: date | None = None
    ) -> list[FxObservation]:
        wanted = [c.upper() for c in currencies if c.upper() != "EUR"]
        if not wanted:
            return []
        params = {"startPeriod": start.isoformat(), "format": "csvdata"}
        if end is not None:
            params["endPeriod"] = end.isoformat()
        response = self._http.request(
            "GET", f"{BASE}/D.{'+'.join(wanted)}.EUR.SP00.A", params=params
        )
        if response.status_code == 404:
            return []  # the API answers 404 when the range holds no observations
        check_status(self.name, response)
        return parse_csv(response.text)

    def deposit_rate(self, start: date, end: date | None = None) -> list[tuple[date, Decimal]]:
        """The ECB deposit facility rate, in percent, one observation per calendar day."""
        return self.series(DEPOSIT_RATE_KEY, start, end)

    def series(self, key: str, start: date, end: date | None = None) -> list[tuple[date, Decimal]]:
        """Any single ECB series by its dataflow and key, e.g. "FM/D.U2.EUR.4F.KR.DFR.LEV"
        (FR-MD-08)."""
        if not key or ".." in key or key.startswith("/"):
            raise ProviderError(f"{key!r} is not an ECB series key such as FLOW/KEY.")
        params = {"startPeriod": start.isoformat(), "format": "csvdata"}
        if end is not None:
            params["endPeriod"] = end.isoformat()
        response = self._http.request("GET", f"{DATA}/{key}", params=params)
        if response.status_code == 404:
            return []
        check_status(self.name, response)
        return parse_rate_csv(response.text)


def parse_rate_csv(text: str) -> list[tuple[date, Decimal]]:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or "OBS_VALUE" not in reader.fieldnames:
        raise ProviderError("The ECB sent a response that could not be read.")
    points: list[tuple[date, Decimal]] = []
    for row in reader:
        raw = (row.get("OBS_VALUE") or "").strip()
        if not raw:
            continue
        try:
            points.append((date.fromisoformat(row["TIME_PERIOD"]), Decimal(raw)))
        except (InvalidOperation, ValueError, KeyError) as exc:
            raise ProviderError("The ECB sent a rate that could not be read.") from exc
    return sorted(points)


def parse_csv(text: str) -> list[FxObservation]:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or "OBS_VALUE" not in reader.fieldnames:
        raise ProviderError("The ECB sent a response that could not be read.")
    observations: list[FxObservation] = []
    for row in reader:
        raw = (row.get("OBS_VALUE") or "").strip()
        if not raw:
            continue
        try:
            observations.append(
                FxObservation(
                    date=date.fromisoformat(row["TIME_PERIOD"]),
                    currency=row["CURRENCY"],
                    rate_per_eur=Decimal(raw),
                )
            )
        except (InvalidOperation, ValueError, KeyError) as exc:
            raise ProviderError("The ECB sent a rate that could not be read.") from exc
    return sorted(observations, key=lambda o: (o.currency, o.date))
