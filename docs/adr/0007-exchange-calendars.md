# ADR 0007: exchange_calendars for trading days and EOD job times

Status: accepted (2026-10-04)

## Context
Nightly closes must be fetched two hours after each exchange closes and skipped on exchange holidays (FR-MD-02). Gap detection and the "stale after 3 trading days" rule (FR-MD-04, FR-MD-11) also need to know which days an exchange was open, including early closes and one-off closures.

## Decision
Use the `exchange_calendars` library, which brings pandas and numpy. Pandas is needed for the analytics in Phase 2 anyway (spec section 4), so the dependency is not extra weight in the end. Calendars are requested from 1999 (the library defaults to 20 years back) so backfills for old purchases work, and rebuilt each calendar year so a long-running worker keeps a future end date.

Exchanges are identified by MIC. OpenFIGI reports Bloomberg codes; the mapping lives in `folio/marketdata/exchanges.py` (Xetra appears as `GR`, see ADR 0006). Trading dates are exchange-local dates; the EOD job time is the session close plus two hours, in the exchange's own timezone, and is `None` on closed days.

## Consequences
Holidays and early closes are never hard-coded. The image grows by the pandas and numpy wheels. Hand-priced instruments use the pseudo exchange `MANUAL`, which has no calendar, no gap check and no staleness flag.
