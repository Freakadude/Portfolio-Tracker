"""Filings with the US Securities and Exchange Commission, read as news (ADR 0062, FR-NW-01).

A company listed in the US (ASML through its Nasdaq listing, TSMC through its ADRs) files its
quarterly results, annual report and other material news with the SEC. EDGAR publishes them as
JSON; this module turns that into the same items a feed gives: a headline, a short summary and
the link, never the whole filing (FR-NW-03). Pure code: the job does the fetching.

* An instrument is matched to an SEC company by its ticker **and** its name (the first word of
  both, without legal suffixes), so a European ticker that happens to equal an unrelated US one
  is never followed.
* Only forms that carry news are kept: current reports (6-K, 8-K), periodic reports (10-Q,
  10-K, 20-F, 40-F) and large-shareholder reports (SC 13D, SC 13G), with their amendments.
* The headline is the press release the filing carries when its cover lists one (exhibit 99.1),
  else the form and what it is about.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from folio.analytics.lookthrough import company_key
from folio.news.feed import FeedItem
from folio.news.normalize import canonical_url, clean_title, plain_text

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{name}"
PER_COMPANY = 5  # newest filings read per company per run
FIRST_DAYS = 30  # how far back the first run looks
SUMMARY_CHARS = 400
FORMS = {"6-K", "8-K", "10-Q", "10-K", "20-F", "40-F", "SC 13D", "SC 13G"}
ITEMS_8K = {
    "1.01": "a material agreement",
    "1.05": "a cybersecurity incident",
    "2.01": "an acquisition or disposal",
    "2.02": "results of operations",
    "2.05": "restructuring costs",
    "2.06": "an impairment",
    "3.01": "a listing notice",
    "4.02": "restated financial statements",
    "5.02": "a change of directors or officers",
    "5.07": "shareholder vote results",
    "7.01": "information for investors",
    "8.01": "other events",
}
ABOUT = {
    "10-Q": "its quarterly report",
    "10-K": "its annual report",
    "20-F": "its annual report",
    "40-F": "its annual report",
    "SC 13D": "a large shareholder's stake",
    "SC 13G": "a large shareholder's stake",
}
_EXHIBIT = re.compile(r"\b99\.1\s+([^,\s].{10,600}?)(?=\s+99\.2\b|\s+SIGNATURES?\b|$)")
_DATED = re.compile(r"[\"”']?\s*,?\s*(press release|presentation)\s+dated\b.*$", re.IGNORECASE)
_QUOTES = "\"'“”‘’"


@dataclass(frozen=True)
class Company:
    cik: int
    ticker: str
    title: str


@dataclass(frozen=True)
class Filing:
    form: str
    accepted: datetime  # UTC
    accession: str  # 0001628280-26-048235
    document: str  # the primary document's file name
    items: str  # 8-K item numbers, "2.02,9.01"

    def folder(self) -> str:
        return self.accession.replace("-", "")

    def index_url(self, cik: int) -> str:
        return ARCHIVE.format(cik=cik, folder=self.folder(), name=f"{self.accession}-index.htm")

    def document_url(self, cik: int) -> str:
        return ARCHIVE.format(cik=cik, folder=self.folder(), name=self.document)


def companies_from(data: Any) -> dict[str, Company]:
    """SEC's list of companies by ticker (upper case)."""
    out: dict[str, Company] = {}
    rows = data.values() if isinstance(data, Mapping) else []
    for row in rows:
        try:
            company = Company(int(row["cik_str"]), str(row["ticker"]).upper(), str(row["title"]))
        except (KeyError, TypeError, ValueError):
            continue
        out.setdefault(company.ticker, company)
    return out


def _first_word(name: str) -> str:
    key = company_key(name, None)
    return key.split()[0] if key else ""


def company_for(companies: Mapping[str, Company], ticker: str | None, name: str) -> Company | None:
    """The SEC company of an instrument, or None. The ticker is read without an exchange suffix
    ("ASML.AS" is ASML), and the names must start with the same word."""
    if not ticker:
        return None
    company = companies.get(ticker.split(".")[0].strip().upper())
    if company is None:
        return None
    return company if _first_word(company.title) == _first_word(name) != "" else None


def _moment(text: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def filings_from(data: Any, since: datetime, limit: int = PER_COMPANY) -> list[Filing]:
    """The news-bearing filings accepted after `since`, at most `limit`, oldest first."""
    try:
        recent = data["filings"]["recent"]
        columns = [
            recent["form"],
            recent["acceptanceDateTime"],
            recent["accessionNumber"],
            recent["primaryDocument"],
        ]
    except (KeyError, TypeError):
        return []
    items = recent.get("items") or [""] * len(columns[0])
    found: list[Filing] = []
    for n, (form, accepted, accession, document) in enumerate(zip(*columns, strict=False)):
        base = str(form).removesuffix("/A")
        moment = _moment(accepted)
        if base not in FORMS or moment is None or moment <= since:
            continue
        found.append(Filing(str(form), moment, str(accession), str(document), str(items[n] or "")))
        if len(found) >= limit:
            break
    return sorted(found, key=lambda f: f.accepted)


def _press_release(text: str) -> str | None:
    """The title of the press release a filing carries, from the exhibit list of its cover."""
    for match in _EXHIBIT.finditer(text):
        title = _DATED.sub("", match.group(1)).strip().strip(_QUOTES).strip()
        if len(title) >= 12:
            return title
    return None


def _about(filing: Filing) -> str:
    base = filing.form.removesuffix("/A")
    if base == "8-K":
        named = [ITEMS_8K[i.strip()] for i in filing.items.split(",") if i.strip() in ITEMS_8K]
        if named:
            return ", ".join(named)
    if base in ABOUT:
        return ABOUT[base]
    words = re.sub(r"\.\w+$", "", filing.document)  # "form6-kquarterlyfilings.htm"
    words = re.sub(r"(?i)^form\s*" + re.escape(base.replace("-", "")), "", words.replace("-", ""))
    words = re.sub(r"[^A-Za-z]+", " ", words).strip().lower()
    return words or "a report"


def item_for(
    instrument_id: int,
    label: str,
    company: Company,
    filing: Filing,
    document: str | None,
) -> FeedItem:
    """One filing as a news item, tagged with the instrument so it links directly."""
    text = plain_text(document, 20_000) if document else ""
    release = _press_release(text) if text else None
    amended = " (amended)" if filing.form.endswith("/A") else ""
    if release:
        title = f"{label}: {release}"
        summary = f"Filed with the SEC as a {filing.form}{amended}: {release}"
    else:
        title = f"{label} filed a {filing.form}{amended}: {_about(filing)}"
        summary = (
            f"{company.title} filed a {filing.form} with the SEC on {filing.accepted:%Y-%m-%d}."
        )
    return FeedItem(
        clean_title(title),
        plain_text(summary, SUMMARY_CHARS),
        canonical_url(filing.index_url(company.cik)),
        filing.accepted,
        (f"instrument:{instrument_id}",),
    )


def since_for(last_fetch: datetime | None, now: datetime) -> datetime:
    """From the last fetch, with a day's overlap (items already stored are skipped), or the last
    month on the first run."""
    if last_fetch is None:
        return now - timedelta(days=FIRST_DAYS)
    return last_fetch - timedelta(days=1)


def user_agent(email: str) -> str:
    """SEC asks every automated reader to say who it is, with a way to reach them."""
    return f"Folio personal portfolio tracker {email.strip()}"


def tagged_instruments(symbols: Sequence[str]) -> list[int]:
    """The instrument ids a feed item was tagged with (`instrument:<id>`)."""
    out: list[int] = []
    for s in symbols:
        kind, _, ident = s.partition(":")
        if kind.lower() == "instrument" and ident.isdigit():
            out.append(int(ident))
    return out
