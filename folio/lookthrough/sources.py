"""Where holdings come from besides an uploaded file: the issuer's CSV address, and EODHD's
fundamentals document (FR-MD-09)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

from folio.imports.parse import MAX_BYTES
from folio.lookthrough.parse import Constituent, HoldingsRead
from folio.marketdata.base import ProviderError
from folio.marketdata.http import HttpClient, check_status


def fetch_issuer_file(http: HttpClient, url: str) -> bytes:
    """Download an issuer's holdings CSV. The address must be http(s); a web page (an issuer's
    download button that needs a click-through) is reported instead of being parsed."""
    if urlparse(url).scheme not in ("http", "https"):
        raise ProviderError("The holdings address must start with http:// or https://.")
    response = http.request("GET", url)
    check_status("issuer", response)
    data = response.content
    if len(data) > MAX_BYTES:
        raise ProviderError("The holdings file is larger than 5 MB.")
    if data.lstrip()[:15].lower().startswith((b"<!doctype", b"<html")):
        raise ProviderError(
            "That address returned a web page, not a CSV file. Use the issuer's direct "
            "download link, or upload the file instead."
        )
    return data


def _dec(value: Any) -> Decimal | None:
    try:
        return None if value is None else Decimal(str(value))
    except InvalidOperation:
        return None


def parse_eodhd_holdings(document: Any) -> HoldingsRead:
    """`ETF_Data.Holdings` of a fundamentals document: a mapping (or list) of constituents with
    Code, Name, Sector, Country and `Assets_%`. EODHD gives no ISIN or currency here."""
    result = HoldingsRead(constituents=[], covered_pct=Decimal(0))
    data = document.get("ETF_Data") if isinstance(document, dict) else None
    holdings = data.get("Holdings") if isinstance(data, dict) else None
    rows = list(holdings.values()) if isinstance(holdings, dict) else holdings
    if not isinstance(rows, list) or not rows:
        result.errors.append(
            "EODHD sent no holdings for this ETF. ETF holdings need its Fundamentals plan."
        )
        return result
    for row in rows:
        if not isinstance(row, dict):
            continue
        weight = _dec(row.get("Assets_%"))
        name = str(row.get("Name") or row.get("Code") or "").strip()
        if weight is None or not name:
            continue
        result.constituents.append(
            Constituent(
                name=name,
                weight_pct=weight,
                ticker=(str(row["Code"]) if row.get("Code") else None),
                sector=(str(row["Sector"]) if row.get("Sector") else None),
                country=(str(row["Country"]) if row.get("Country") else None),
            )
        )
    result.covered_pct = sum((c.weight_pct for c in result.constituents), Decimal(0))
    if not result.constituents:
        result.errors.append("EODHD's holdings had no readable weights.")
    elif result.covered_pct > Decimal("105"):
        result.errors.append(f"EODHD's weights add up to {result.covered_pct:.1f} %.")
    elif result.covered_pct < Decimal("98"):
        result.warnings.append(f"EODHD lists {result.covered_pct:.1f} % of the fund.")
    return result
