"""Adapters against stored responses. Yahoo, OpenFIGI and ECB tests use responses recorded
from the live APIs; EODHD and Twelve Data use documentation-derived fixtures (see
tests/fixtures/providers/README.md)."""

from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest

from folio.marketdata.base import ListingRef, NotSupported, ProviderError, SymbolNotFound
from folio.marketdata.ecb import EcbRates, parse_csv
from folio.marketdata.eodhd import EodhdProvider
from folio.marketdata.openfigi import FigiMapper
from folio.marketdata.twelvedata import TwelveDataProvider
from folio.marketdata.yahoo import YahooProvider
from tests.marketdata_helpers import Scripted, client, fixture_text, respond

D = Decimal


def listing(**symbols: str) -> ListingRef:
    return ListingRef(1, "XETR", "SXR8", "EUR", symbols, "IE00B5BMR087")


# --- Yahoo (recorded) --------------------------------------------------------------------------


def yahoo(routes: dict[str, str], status: int = 200) -> tuple[YahooProvider, Scripted]:
    def handler(request: httpx.Request) -> httpx.Response:
        for fragment, name in routes.items():
            if fragment in str(request.url):
                return respond(name, status)
        return httpx.Response(404, json={})

    scripted = Scripted(handler)
    return YahooProvider(client("yahoo", scripted)), scripted


def test_yahoo_daily_bars_match_the_recorded_response() -> None:
    provider, scripted = yahoo({"/chart/SXR8.DE": "yahoo_sxr8_de.json"})
    bars = provider.get_eod(listing(yahoo="SXR8.DE"), date(2024, 1, 1), date(2024, 1, 12))
    assert [b.date for b in bars] == [
        date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5),
        date(2024, 1, 8), date(2024, 1, 9), date(2024, 1, 10), date(2024, 1, 11),
    ]  # fmt: skip
    first = bars[0]
    # binary-float artefacts in the recording (454.19000244140625) are rounded to 4 decimals
    assert (first.close, first.open, first.high, first.low) == (
        D("454.1900"), D("454.8800"), D("455.0400"), D("453.0000"),
    )  # fmt: skip
    assert first.adj_close == D("454.1900") and first.volume == D(65691)
    request = scripted.requests[0]
    assert request.url.params["interval"] == "1d"
    assert request.url.params["period1"] == "1704067200"  # 2024-01-01 00:00 UTC
    assert request.url.params["period2"] == "1705104000"  # the end day is inclusive


def test_yahoo_dividends_and_splits_from_recorded_events() -> None:
    provider, _ = yahoo(
        {"/chart/ASML.AS": "yahoo_asml_as_2024.json", "/chart/AAPL": "yahoo_aapl_split.json"}
    )
    dividends = provider.get_dividends(
        listing(yahoo="ASML.AS"), date(2024, 1, 1), date(2024, 12, 31)
    )
    assert [(d.ex_date, d.amount, d.currency) for d in dividends] == [
        (date(2024, 2, 5), D("1.45"), "EUR"),
        (date(2024, 4, 26), D("1.75"), "EUR"),
        (date(2024, 7, 29), D("1.52"), "EUR"),
        (date(2024, 10, 29), D("1.52"), "EUR"),
    ]
    splits = provider.get_splits(listing(yahoo="AAPL"), date(2020, 8, 25), date(2020, 9, 3))
    assert [(s.ex_date, s.ratio) for s in splits] == [(date(2020, 8, 31), D(4))]


def test_yahoo_probe_confirms_the_trading_currency() -> None:
    provider, _ = yahoo({"/chart/SXR8.DE": "yahoo_sxr8_de.json"})
    meta = provider.probe("SXR8.DE")
    assert meta is not None
    assert (meta.currency, meta.timezone, meta.instrument_type) == ("EUR", "Europe/Berlin", "ETF")
    assert meta.exchange_name == "XETRA"


def test_yahoo_unknown_symbol_and_missing_mapping() -> None:
    provider, _ = yahoo({"/chart/NOPE": "yahoo_not_found.json"}, status=404)
    with pytest.raises(SymbolNotFound, match="Yahoo does not know the symbol NOPE"):
        provider.get_eod(listing(yahoo="NOPE"), date(2024, 1, 1), date(2024, 1, 5))
    with pytest.raises(SymbolNotFound, match="No yahoo symbol is known for SXR8"):
        provider.get_eod(listing(eodhd="SXR8.XETRA"), date(2024, 1, 1), date(2024, 1, 5))


def test_yahoo_error_inside_a_200_response_is_reported() -> None:
    provider, _ = yahoo({"/chart/GONE": "yahoo_not_found.json"})  # HTTP 200 with an error body
    with pytest.raises(SymbolNotFound, match="symbol may be delisted"):
        provider.probe("GONE")


def test_yahoo_search_by_isin_finds_the_milan_listing_only() -> None:
    provider, _ = yahoo({"/v1/finance/search": "yahoo_search_sxr8.json"})
    hits = provider.search("IE00B5BMR087")
    assert [(h.symbol, h.exchange_code, h.instrument_type) for h in hits] == [
        ("CSSPX.MI", "MIL", "ETF")
    ]


# --- OpenFIGI (recorded) -----------------------------------------------------------------------


def figi(name: str) -> FigiMapper:
    return FigiMapper(client("openfigi", Scripted(lambda r: respond(name))), api_key="k")


def test_openfigi_maps_the_isin_to_exchange_listings() -> None:
    listings = figi("openfigi_sxr8.json").map_isin("IE00B5BMR087")
    assert len(listings) == 275
    by_exchange = {}
    for item in listings:
        by_exchange.setdefault(item.exch_code, set()).add(item.ticker)
    # The recording shows Xetra's SXR8 under "GR" (there is no "GY") and Amsterdam under "NA".
    assert "SXR8" in by_exchange["GR"] and "CSPX" in by_exchange["NA"]
    assert by_exchange["LN"] >= {"CSPX"} and by_exchange["IM"] == {"CSSPX"}
    sample = next(i for i in listings if i.exch_code == "NA")
    assert (sample.security_type, sample.market_sector) == ("ETP", "Equity")


def test_openfigi_sends_the_isin_and_the_key() -> None:
    scripted = Scripted(lambda r: respond("openfigi_sxr8.json"))
    FigiMapper(client("openfigi", scripted), api_key="secret-key").map_isin("IE00B5BMR087")
    request = scripted.requests[0]
    assert request.headers["x-openfigi-apikey"] == "secret-key"
    assert request.read() == b'[{"idType":"ID_ISIN","idValue":"IE00B5BMR087"}]'


def test_openfigi_real_error_and_documented_warning() -> None:
    with pytest.raises(ProviderError, match="Invalid idValue format"):
        figi("openfigi_notfound.json").map_isin("XX0000000000")
    assert figi("openfigi_warning.json").map_isin("IE0000000000") == []


# --- ECB (recorded) ----------------------------------------------------------------------------


def test_ecb_rates_parse_the_recorded_csv() -> None:
    observations = parse_csv(fixture_text("ecb_exr.csv"))
    gbp = {o.date: o.rate_per_eur for o in observations if o.currency == "GBP"}
    usd = {o.date: o.rate_per_eur for o in observations if o.currency == "USD"}
    assert gbp[date(2024, 12, 24)] == D("0.82805")
    assert set(gbp) == set(usd)
    # published on TARGET working days only: no weekends, 25/26 December or 1 January
    for missing in (date(2024, 12, 21), date(2024, 12, 22), date(2024, 12, 25), date(2024, 12, 26),
                    date(2025, 1, 1)):  # fmt: skip
        assert missing not in gbp
    assert min(gbp) == date(2024, 12, 20) and max(gbp) == date(2025, 1, 6) and len(gbp) == 9


def test_ecb_fetch_builds_the_series_key_and_range() -> None:
    scripted = Scripted(lambda r: respond("ecb_exr.csv", content_type="text/csv"))
    rates = EcbRates(client("ecb", scripted)).fetch(
        ["usd", "GBP", "EUR"], date(2024, 12, 20), date(2025, 1, 6)
    )
    assert len(rates) > 10
    url = scripted.requests[0].url
    assert url.path.endswith("/EXR/D.USD+GBP.EUR.SP00.A")
    assert dict(url.params) == {
        "startPeriod": "2024-12-20",
        "endPeriod": "2025-01-06",
        "format": "csvdata",
    }
    assert (
        EcbRates(client("ecb", scripted)).fetch(["EUR"], date(2024, 1, 1)) == []
    )  # nothing to fetch


def test_ecb_outage_page_is_a_provider_error_after_retries() -> None:
    scripted = Scripted(lambda r: respond("ecb_outage_504.html", 504, "text/html"))
    with pytest.raises(ProviderError, match="ecb did not answer after 3 attempts"):
        EcbRates(client("ecb", scripted)).fetch(["USD"], date(2024, 12, 20))
    assert len(scripted.requests) == 3


def test_ecb_html_instead_of_csv_is_rejected() -> None:
    with pytest.raises(ProviderError, match="could not be read"):
        parse_csv(fixture_text("ecb_outage_504.html"))


# --- EODHD (documentation-derived) -------------------------------------------------------------


def eodhd(routes: dict[str, str]) -> tuple[EodhdProvider, Scripted]:
    def handler(request: httpx.Request) -> httpx.Response:
        for fragment, name in routes.items():
            if fragment in request.url.path:
                return respond(name)
        return httpx.Response(404, json={})

    scripted = Scripted(handler)
    return EodhdProvider(client("eodhd", scripted), "token-123"), scripted


def test_eodhd_eod_sorts_skips_empty_closes_and_keeps_exact_decimals() -> None:
    provider, scripted = eodhd({"/eod/SXR8.XETRA": "eodhd_eod.json"})
    bars = provider.get_eod(listing(eodhd="SXR8.XETRA"), date(2024, 1, 1), date(2024, 1, 5))
    assert [(b.date, b.close) for b in bars] == [
        (date(2024, 1, 2), D("454.19")),
        (date(2024, 1, 3), D("453.03")),
    ]  # the 4 January row without a close is dropped
    params = scripted.requests[0].url.params
    assert (params["from"], params["to"], params["api_token"]) == (
        "2024-01-01",
        "2024-01-05",
        "token-123",
    )


def test_eodhd_search_gives_currency_per_listing() -> None:
    provider, _ = eodhd({"/search/IE00B5BMR087": "eodhd_search.json"})
    hits = provider.search("IE00B5BMR087")
    assert [(h.symbol, h.currency) for h in hits] == [("SXR8.XETRA", "EUR"), ("CSPX.AS", "USD")]
    assert hits[0].isin == "IE00B5BMR087"


def test_eodhd_splits_dividends_and_quotes() -> None:
    provider, _ = eodhd(
        {
            "/splits/": "eodhd_splits.json",
            "/div/": "eodhd_div.json",
            "/real-time/": "eodhd_realtime.json",
        }
    )
    ref = listing(eodhd="SXR8.XETRA")
    splits = provider.get_splits(ref, date(2020, 1, 1), date(2024, 1, 1))
    assert [(s.ex_date, s.ratio) for s in splits] == [
        (date(2020, 8, 31), D(4)),
        (date(2022, 6, 6), D("0.5")),
    ]  # "1/2" is a reverse split: one new unit for two old ones
    dividends = provider.get_dividends(ref, date(2024, 1, 1), date(2024, 12, 31))
    assert [(d.ex_date, d.amount) for d in dividends] == [
        (date(2024, 2, 5), D("1.45")),
        (date(2024, 4, 26), D("1.75")),
    ]
    quote = provider.get_quotes([ref])[1]
    assert quote.price == D("456.15") and quote.ts == datetime(2024, 1, 11, 16, 10, tzinfo=UTC)


def test_eodhd_rejected_key_and_unknown_symbol() -> None:
    denied = EodhdProvider(client("eodhd", Scripted(lambda r: httpx.Response(401, json={}))), "bad")
    with pytest.raises(ProviderError, match="Check the API key"):
        denied.get_eod(listing(eodhd="X.XETRA"), date(2024, 1, 1), date(2024, 1, 2))
    missing = EodhdProvider(client("eodhd", Scripted(lambda r: httpx.Response(404, json={}))), "k")
    with pytest.raises(SymbolNotFound, match="EODHD does not know"):
        missing.get_eod(listing(eodhd="X.XETRA"), date(2024, 1, 1), date(2024, 1, 2))


# --- Twelve Data (documentation-derived) -------------------------------------------------------


def twelvedata(name: str) -> TwelveDataProvider:
    return TwelveDataProvider(client("twelvedata", Scripted(lambda r: respond(name))), "key")


def test_twelvedata_time_series() -> None:
    bars = twelvedata("twelvedata_time_series.json").get_eod(
        listing(twelvedata="AAPL"), date(2024, 1, 2), date(2024, 1, 3)
    )
    assert [(b.date, b.close, b.volume) for b in bars] == [
        (date(2024, 1, 2), D("185.64000"), D(82488700)),
        (date(2024, 1, 3), D("184.25000"), D(58414500)),
    ]


def test_twelvedata_errors_arrive_as_http_200_with_a_code() -> None:
    ref = listing(twelvedata="SXR8")
    with pytest.raises(SymbolNotFound, match="symbol"):
        twelvedata("twelvedata_error_404.json").get_eod(ref, date(2024, 1, 1), date(2024, 1, 2))
    with pytest.raises(ProviderError, match="not available on your plan"):
        twelvedata("twelvedata_error_plan.json").get_eod(ref, date(2024, 1, 1), date(2024, 1, 2))


def test_twelvedata_quote_and_unsupported_operations() -> None:
    provider = twelvedata("twelvedata_quote.json")
    assert provider.get_quotes([listing(twelvedata="AAPL")])[1].price == D("184.25000")
    for call in (
        lambda: provider.get_splits(listing(), date(2024, 1, 1), date(2024, 1, 2)),
        lambda: provider.get_dividends(listing(), date(2024, 1, 1), date(2024, 1, 2)),
        lambda: provider.search("x"),
    ):
        with pytest.raises(NotSupported):
            call()
    assert provider.probe("AAPL") is None
