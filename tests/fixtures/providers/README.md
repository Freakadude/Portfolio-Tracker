# Provider fixtures

No test makes a live call. Each adapter is tested against a stored response.

## Recorded from the live APIs (2026-10-04)

These are the real responses (only a final newline was added by a formatting hook), so the
adapters are proven against the real formats:

- `yahoo_sxr8_de.json` - daily bars for SXR8.DE (Xetra), 2024-01-01 to 2024-01-12
- `yahoo_asml_as_2024.json` - ASML.AS for 2024, including the four dividend events
- `yahoo_aapl_split.json` - AAPL around the 4-for-1 split on 2020-08-31
- `yahoo_search_sxr8.json` - Yahoo search by ISIN (finds only the Milan listing, which is why
  symbol resolution starts from OpenFIGI)
- `openfigi_sxr8.json` - OpenFIGI mapping for IE00B5BMR087 (275 listings; the Xetra listing is
  reported under exchange code `GR`, Euronext Amsterdam under `NA`)
- `openfigi_notfound.json` - OpenFIGI's real answer to a malformed ISIN
- `ecb_exr.csv` - ECB reference rates for USD and GBP, 2024-12-20 to 2025-01-06
- `ecb_outage_504.html` - the ECB data portal's real HTML outage page (HTTP 504)

## Derived from the providers' documentation (NOT recorded)

No API key was available when these adapters were written. The shapes follow the public
documentation and must be checked against a real response once a key exists:

- `eodhd_*.json` - EODHD EOD, search, dividends, splits and real-time responses, and
  `eodhd_fundamentals_etf.json`, the `ETF_Data.Holdings` part of a fundamentals document (invented
  constituents)
- `twelvedata_*.json` - Twelve Data time series, quote and error responses
- `openfigi_warning.json` - OpenFIGI's "No identifier found." shape
- `yahoo_not_found.json` - the shape of Yahoo's error body (written from memory of the format)
- `fred_dfii10.json`, `fred_dtwexbgs.json` - FRED `series/observations` responses in the documented
  JSON shape, with invented values (one holiday marked ".", as FRED does); `fred_error_400.json`
  and `fred_error_series.json` - FRED's documented error bodies for an unregistered key and an
  unknown series

When a real response differs, replace the fixture with the recording and fix the adapter.

News fixtures live in `tests/fixtures/news/`: `ecb_press.xml` and `fed_press_all.xml` are
**recorded** from the ECB's and the Federal Reserve's live feeds on 2026-10-05 (the Fed's cut to
its first 8 items); `atom_example.xml` and `robots_example.txt` are invented. The EODHD news
response (`providers/eodhd_news.json`) is derived from its documentation and must be checked
against a real response once a key exists.

Anthropic responses in agent tests are built in `tests/agent_helpers.py` from the Messages API
documentation (text, tool_use, server_tool_use and web_search_tool_result blocks, and the
usage fields); none was recorded from the live API. The official SDK builds and parses the
requests and responses for real; only the network is replaced (an `httpx2` mock transport).

