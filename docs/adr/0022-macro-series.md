# ADR 0022: Macro series from FRED and the ECB

Status: accepted (2026-10-05)

## Decisions
- **Two sources, no new dependency.** FRED (`series/observations`, JSON, free API key) gives the US series the strategy watches: the 10-year real yield (DFII10), the broad trade-weighted dollar (DTWEXBGS) and the Fed funds rate (DFF). The ECB adapter, which already fetched the deposit facility rate, now fetches any SDMX series by its dataflow and key. Both go through the shared HTTP client with its retries, daily budgets and circuit breaker. FRED's error message about an unknown key repeats the key, so the adapter replaces it with "the API key is not valid" before it can reach a log or the UI.
- **A list in Settings, plus what the strategies name.** Settings, Macro holds the daily list (the four series above by default). The active and shadow strategies' `macro_series` are fetched too, so a rule never waits for data nobody fetches. Series are stored by their source code (`DFII10`, `ECB_DFR`, or an ECB key) in the Phase 2 `macro_series` and `macro_point` tables, idempotently, re-reading the last week so revisions land.
- **No key, no failure.** Without a FRED key the FRED series are skipped and the run says how to add one; the job is not marked failed for a missing optional key. A series the provider refuses fails the run (shown on the System page) but the others are still stored, and the rules run afterwards either way.
- **The daily job runs at 07:00 Amsterdam time**, after FRED's overnight update; the ECB deposit rate is also refreshed by the afternoon FX job, as before. The rules run right after, so a `macro_threshold` rule sees the new value the same morning.
- **The fixtures are derived, not recorded.** No FRED key was available; the responses follow the documented JSON shape with invented values and must be replaced by a recording once a key exists (tests/fixtures/providers/README.md).
- **The Macro overlay widget** draws up to two series and optionally one position, each in its own pane on a shared time axis, never two y-scales on one plot.

## Consequences
The owner needs a free FRED key for the US series; the ECB series work without one.
