# ADR 0006: Market-data providers

Status: accepted (2026-10-04)

## Context
Phase 1 needs free-tier prices for Xetra and Euronext Amsterdam listings (Q2: free tiers). The spec's free options do not cover this: EODHD's free plan allows 20 calls a day and one year of history, and Twelve Data's free plan covers US markets only.

## Decisions
- **Yahoo Finance is enabled by default** (owner decision, 2026-10-04), at priority 2 behind EODHD once an EODHD key exists. It is unofficial and can break, so every bar records its source and stale prices are flagged. The spec default was "built but off".
- **The Yahoo adapter calls the public chart API through httpx**, not the `yfinance` package: fewer dependencies, and the response format is under our control and covered by recorded fixtures.
- **Adapters are synchronous.** A portfolio of about ten listings makes a handful of calls a day, jobs run on APScheduler threads, and the database layer is synchronous. Async would add complexity without benefit at this scale.
- **Symbol resolution starts from OpenFIGI, not from a price provider.** The recorded OpenFIGI response for IE00B5BMR087 reports the Xetra listing under exchange code `GR` (there is no `GY`) and Euronext Amsterdam under `NA`; Yahoo's search by ISIN finds only the Milan listing. OpenFIGI does not state the trading currency, so each candidate's currency is confirmed by a provider probe (Yahoo chart metadata, or EODHD search when a key exists), and shown as a guess in the picker when no provider could confirm it.
- **Every attempt is counted.** The call budget is charged before each HTTP attempt, including retries, with a single conditional UPDATE so concurrent processes cannot exceed the limit. A budget of 0 means unlimited.
- **A circuit breaker** pauses a provider for 15 minutes after three consecutive failed calls, so a provider that is down is not hammered.
- **Fixtures.** Yahoo, OpenFIGI and ECB tests use responses recorded from the live APIs on 2026-10-04. EODHD and Twelve Data fixtures are derived from their documentation because no keys were available; they are flagged in `tests/fixtures/providers/README.md` and must be checked against a real response once a key exists.

## Consequences
With no keys at all, prices come from Yahoo. Adding an EODHD key makes it the primary source without code changes. If Yahoo changes its API, the fallback chain reports the failure and prices go stale rather than wrong.
